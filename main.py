import asyncio
import logging
import sys

from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential
from odk_tools.tracking import Tracker
from dubu_client import DubuClientManager
from active_directory.client import ActiveDirectoryClient
from services.mail_service import MailService, extract_text_from_html, parse_email_data
from services.utils import calculate_age_from_cpr, setup_logging

tracker: Tracker
dubu: DubuClientManager
mail_service: MailService
ad_client: ActiveDirectoryClient
proces_navn = "Journalisering af opmærksomhedsskemaer i DUBU"


async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    # Get messages from inbox
    try:
        messages = await mail_service.check_inbox_messages(limit=100, mailbox_address="rpa.bfr@odense.dk")
        logger.info(f"Found {len(messages)} messages in inbox")
        
        # Filter for emails from specific senders
        godkendte_afsendere = ["xflow@odense.dk"]
        
        for message in messages:
            if workqueue.get_item_by_reference(message['internet_message_id']): # Check om mail allerede i workqueue
                logger.debug(f"Message {message['internet_message_id']} already in workqueue, skipping")
                continue
            afsender_email = message['from_address'].lower()
            
            # Skip messages not from allowed senders
            if afsender_email not in godkendte_afsendere:
                continue
                        
            # Get full email body
            body_data = await mail_service.get_message_body("rpa.bfr@odense.dk", message['id'])

            if body_data:
                content_type = body_data['content_type']
                content = body_data['content']
                
                # Convert HTML to plain text if needed
                if content_type.lower() == 'html':
                    ren_tekst = extract_text_from_html(content)
                else:
                    ren_tekst = content
                
                # Extract structured data from email
                workqueue_data = parse_email_data(ren_tekst)
                workqueue_data["email_id"] = message['id']

                # Calculate age from CPR number
                # if 'cpr_nr' in workqueue_data:
                #     age = calculate_age_from_cpr(workqueue_data['cpr_nr'])
                #     workqueue_data['alder'] = age
                # # Hvis borger er >= 15, så skip
                
                if workqueue_data.get('alder', 0) >= 15:
                    continue

                workqueue.add_item(
                    data=workqueue_data,
                    reference=message['internet_message_id']
                )
                   
    except Exception as e:
        logger.error(f"Error checking inbox: {e}")

async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
 
            try:
                borger_sag = dubu.sager.soeg_sager(
                    query=data.get('cpr_nr', '')
                )

                # Test Borger
                # borger_sag = dubu.sager.soeg_sager(
                #     query="2222222222",                 
                # )
                
                borger_sag = borger_sag["value"][0]

                # Opret aktivitet i DUBU
                oprettet_aktivitet = dubu.aktiviteter.opret_aktivitet(
                    sags_id=borger_sag["id"],
                    type="Statusudtalelse",
                    undertype=data.get("lokation", "Ukendt"),
                    beskrivelse="Modtaget opmærksomhedsskema",
                    status="Aktiv",
                    notat=f"Modtaget opmærksomhedsskema fra {data.get('navn', '')}<br/>//Journaliseret af Robot A"
                )

                email_id = data.get('email_id')
                if not email_id:
                    raise WorkItemError("email_id mangler i work item data")

                attachment = await mail_service.get_first_file_attachment_bytes(
                    mailbox_address="rpa.bfr@odense.dk",
                    message_id=email_id
                )

                if not attachment:
                    raise WorkItemError("Ingen vedhæftet fil fundet på mailen")

                attachment_name, upload_bytes, _ = attachment
                
                uploaded_dokument = dubu.dokumenter.upload_dokument_til_aktivitet(
                    sags_id=borger_sag["id"],
                    dokument_titel=f" Opmærksomhedsskema {data.get('navn', '')}" ,
                    filnavn=attachment_name or "RPA_aflevering_til_postkasse.pdf",
                    dokument=upload_bytes,
                    aktivitet=oprettet_aktivitet
                )

                if not uploaded_dokument:
                    raise WorkItemError("Dokument upload mislykkedes")
                                
                modtager = dubu.brugere.soeg_modtager_bruger(borger_sag["primaerBehandler"]["navn"], str(borger_sag["primaerBehandler"]["email"]).split("@")[0])

                if modtager is None:
                    raise WorkItemError("Modtager ikke fundet i DUBU")

                sag = dubu._client.get(f"api/sager/{borger_sag['id']}").json()

                dubu.advisering.opret_advisering(
                    sags_reference=sag["sagReference"],
                    titel="Opmærksomhedsskema modtaget",
                    type="PersonligAdvisering",
                    ansvar="Sagsbehandler",
                    beskrivelse=f"Et opmærksomhedsskema er modtaget og journaliseret for CPRnr: {data.get('cpr_nr', 'N/A')} på <a href='https://www.dubu.dk/#/aktivitet/{oprettet_aktivitet['id']}'>aktiviteten</a>",
                    modtager=modtager
                )

                # attributes = ['displayName', 'mail', 'odkLeder']
                # leder = ad_client.søg(søgefilter=f"(sAMAccountName={str(borger_sag['primaerBehandler']['email']).split('@')[0]})", attributes=attributes)
                # if not leder or not leder[0]['odkLeder'].value:
                #     # Overvej at skippe leder advisering i stedet
                #     raise WorkItemError("Leder ikke fundet i Active Directory")

                # leder_samaccountname = leder[0]['odkLeder'].value
                # leder = ad_client.søg(
                #     søgefilter=f"(sAMAccountName={leder_samaccountname})",
                #     attributes=attributes,
                # )

                # leder = leder[0] if leder else None
                
                # if not leder:
                #     raise WorkItemError("Leder ikke fundet i Active Directory")

                # leder = dubu.brugere.soeg_modtager_bruger(leder['displayName'].value, leder_samaccountname)
                
                # dubu.advisering.opret_advisering(
                #     sags_reference=sag["sagReference"],
                #     titel="Opmærksomhedsskema modtaget",
                #     type="PersonligAdvisering",
                #     ansvar="Ledelse",
                #     beskrivelse=f"Primær sagsbehandler er {borger_sag['primaerBehandler']['navn']}. Se aktivitet <a href='https://www.dubu.dk/#/aktivitet/{oprettet_aktivitet['id']}'>her</a>",
                #     modtager=leder
                # )                

                behandlet_mappe = await mail_service._find_folder_by_name(mailbox_address="rpa.bfr@odense.dk", folder_name="Journaliseret opmærksomhedsskema")

                if not behandlet_mappe:
                    raise WorkItemError("Mappen 'Journaliseret opmærksomhedsskema' blev ikke fundet i mailboksen")

                # Flyt mail til mappe "Journaliseret opmærksomhedsskema"
                await mail_service.move_message(
                    "rpa.bfr@odense.dk", data['email_id'], behandlet_mappe['id'])
            except WorkItemError as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                logger.error(f"Error processing item: {data}. Error: {e}")
                item.fail(str(e))


def initialize_sync_services():
    """Initialize synchronous services before async context."""
    # Initialize Automation Server first (needed for credentials)
    ats = AutomationServer.from_environment()
    
    # Initialize external systems for automation here..
    tracking_credential = Credential.get_credential("Odense SQL Server")
    roboa_credential = Credential.get_credential("RoboA") # bruges til at logge ind på DUBU
    roboc_credential = Credential.get_credential("RoboC") # bruges til at hente emails

    tracker = Tracker(
        username=tracking_credential.username, 
        password=tracking_credential.password
    )

    dubu = DubuClientManager(
        username=f"{roboa_credential.username}@odense.dk",
        password=roboa_credential.password,
        idp=roboa_credential.data["idp"]
    )
    
    ad_client = ActiveDirectoryClient(
        server_url=roboa_credential.data["ad_server_url"],
        port=int(roboa_credential.data["ad_server_port"]),
        base_dn=roboa_credential.data["ad_server_base_dn"],
        username=f"{roboa_credential.username}@odense.dk",
        password=roboa_credential.password
    )
        

    return tracker, dubu, ats, roboc_credential, ad_client


async def main(tracker, dubu, ats, roboc_credential):
    """Main entry point."""
    logger = logging.getLogger(__name__)
    
    logger.info(f"Starting: {proces_navn}")
    
    global mail_service
    
    # Initialize mail service (async)
    mail_service = MailService(roboc_credential)
    await mail_service.initialize()
    logger.debug("Mail service initialized successfully")
    
    workqueue = ats.workqueue()
    # Queue management
    if "--queue" in sys.argv:
        workqueue.clear_workqueue("new")
        await populate_queue(workqueue)
        exit(0)

    # Process workqueue
    await process_workqueue(workqueue)


if __name__ == "__main__":
    # Setup logging FIRST
    setup_logging()
    
    # Initialize sync services BEFORE starting asyncio
    tracker, dubu, ats, roboc_credential, ad_client = initialize_sync_services()
    
    # Now run async code
    asyncio.run(main(tracker, dubu, ats, roboc_credential))
