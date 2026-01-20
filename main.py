import asyncio
import logging
import os
import sys

from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential, WorkItemStatus
from odk_tools.tracking import Tracker
from dubu_client import DubuClientManager

from services.mail_service import MailService, extract_text_from_html, parse_email_data
from services.utils import calculate_age_from_cpr, setup_logging

tracker: Tracker
dubu: DubuClientManager
mail_service: MailService

proces_navn = "Journalisering af opmærksomhedsskemaer i DUBU"


async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.debug("Checking email inbox for new items...")
    
    # Get messages from inbox
    try:
        messages = await mail_service.check_inbox_messages(limit=10)
        logger.info(f"Found {len(messages)} messages in inbox")
        
        # Filter for emails from specific senders
        godkendte_afsendere = ["gtp@odense.dk", "xflow@odense.dk", "jakkw@odense.dk"]
        
        for message in messages:
            if workqueue.get_item_by_reference(message['internet_message_id']): # Check om mail allerede i workqueue
                logger.debug(f"Message {message['internet_message_id']} already in workqueue, skipping")
                continue
            afsender_email = message['from_address'].lower()
            
            # Skip messages not from allowed senders
            if afsender_email not in godkendte_afsendere:
                continue
            
            # Skip messages that don't contain "RPA" in subject
            if "RPA" not in message['subject']:
                continue
                        
            # Get full email body
            body_data = await mail_service.get_message_body(f"{roboc_credential.username}@odense.dk", message['id'])
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
                if 'cpr_nr' in workqueue_data:
                    age = calculate_age_from_cpr(workqueue_data['cpr_nr'])
                    workqueue_data['alder'] = age
                # Hvis borger er >= 15, så skip
                # if workqueue_data.get('alder', 0) >= 15:
                #     continue

                # Extract attachments from email
                if message['has_attachments']:
                    attachments = await mail_service.list_attachments(f"{roboc_credential.username}@odense.dk", message['id'])
                    logger.info(f"Found {len(attachments)} attachments:")
                    for filename, temp_path, metadata in attachments:
                        
                        # Look for the specific PDF file
                        if filename == "RPA_aflevering_til_postkasse.pdf":
                            workqueue_data['pdf_path'] = temp_path
            
            workqueue.add_item(
                data=workqueue_data,
                reference=message['internet_message_id']
            )
                   
    except Exception as e:
        logger.error(f"Error checking inbox: {e}")

async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
 
            try:

                borger = dubu.sager.soeg_sager(
                    query=data.get('cpr_nr', '')
                )
                # test testesen:
                borger = dubu.sager.soeg_sager(query="2222222222")

                # Opret aktivitet i DUBU
                oprettet_aktivitet = dubu.aktiviteter.opret_aktivitet(
                    sags_id=borger["value"][0]["id"],
                    type="Statusudtalelse",
                    undertype="Skole", # Skal også replaces på et tidspunkt
                    beskrivelse="Modtaget opmærksomhedsskema",
                    status="Aktiv", # hvad er det?
                    notat=f"Automatisk oprettet aktivitet for CPRnr: {data.get('cpr_nr', 'N/A')} og lokation: {data.get('lokation', 'N/A')}"
                )

                # Tilføj dokument til DUBU
                with open(data['pdf_path'], 'rb') as pdf_file:
                    upload_bytes = pdf_file.read()
                
                uploaded_dokument = dubu.dokumenter.upload_dokument_til_aktivitet(
                    sags_id=borger["value"][0]["id"],
                    dokument_titel="RPA Aflevering til postkasse" ,
                    filnavn="RPA_aflevering_til_postkasse.pdf",
                    dokument=upload_bytes,
                    aktivitet=oprettet_aktivitet
                )

                if not uploaded_dokument:
                    raise WorkItemError("Dokument upload mislykkedes")
                

                # Find all mapper i indbakken
                mapper = await mail_service.list_shared_mailbox_folders(f"{roboc_credential.username}@odense.dk")

                # Find mappe "Opmærksomhedsskemaer - behandlet"
                behandlet_mappe_id = None
                for mappe in mapper:
                    if mappe['display_name'] == "Opmærksomhedsskemaer - behandlet":
                        behandlet_mappe_id = mappe['id']
                        break

                # Flyt mail til mappe "Opmærksomhedsskemaer - behandlet"
                await mail_service.move_message(
                    f"{roboc_credential.username}@odense.dk", data['email_id'], behandlet_mappe_id)                


                print("howdy")
                # fjern temp fil:
                os.remove(data['pdf_path'])
                # Process the item here
                pass
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
    
    return tracker, dubu, ats, roboc_credential


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
    tracker, dubu, ats, roboc_credential = initialize_sync_services()
    
    # Now run async code
    asyncio.run(main(tracker, dubu, ats, roboc_credential))
