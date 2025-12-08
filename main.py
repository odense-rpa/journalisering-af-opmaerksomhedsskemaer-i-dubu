import asyncio
import logging
import os
import sys

from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential
from odk_tools.tracking import Tracker
from dubu_client import DubuClientManager

from config import settings
from services.mail_service import MailService, extract_text_from_html, parse_email_data

tracker: Tracker
dubu: DubuClientManager
mail_service: MailService

proces_navn = "Journalisering af opmærksomhedsskemaer i DUBU"


def setup_logging():
    """Setup logging configuration."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


async def populate_queue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Checking email inbox for new items...")
    
    # Get messages from inbox
    try:
        messages = await mail_service.check_inbox_messages(limit=10)
        logger.info(f"Found {len(messages)} messages in inbox")
        
        # Filter for emails from specific senders
        allowed_senders = ["gtp@odense.dk", "xflow@odense.dk", "jakkw@odense.dk"]
        
        for message in messages:
            from_address = message['from_address'].lower()
            
            # Skip messages not from allowed senders
            if from_address not in allowed_senders:
                logger.debug(f"Skipping message from {from_address} (not in allowed senders)")
                continue
            
            # Skip messages that don't contain "RPA" in subject
            if "RPA" not in message['subject']:
                logger.debug(f"Skipping message with subject '{message['subject']}' (RPA not found)")
                continue
            
            logger.info(f"Subject: {message['subject']}")
            logger.info(f"From: {message['from_name']} ({message['from_address']})")
            logger.info(f"Received: {message['received_date_time']}")
            logger.info(f"Has attachments: {message['has_attachments']}")
            logger.info(f"Body preview: {message['body_preview']}")
            
            # Get full email body
            body_data = await mail_service.get_message_body(settings.username, message['id'])
            if body_data:
                content_type = body_data['content_type']
                content = body_data['content']
                
                # Convert HTML to plain text if needed
                if content_type.lower() == 'html':
                    plain_text = extract_text_from_html(content)
                else:
                    plain_text = content
                
                # Extract structured data from email
                extracted_data = parse_email_data(plain_text)

                
                logger.info(f"Extracted data:")
                logger.info(f"  Indsendt dato: {extracted_data.get('indsendt_dato', 'N/A')}")
                logger.info(f"  CPR-nr: {extracted_data.get('cpr_nr', 'N/A')}")
                logger.info(f"  Lokation: {extracted_data.get('lokation', 'N/A')}")
                
                # Extract attachments from email
                if message['has_attachments']:
                    attachments = await mail_service.list_attachments(settings.username, message['id'])
                    logger.info(f"Found {len(attachments)} attachments:")
                    for filename, temp_path, metadata in attachments:
                        logger.info(f"  - {filename} ({metadata['size']} bytes) -> {temp_path}")
                        
                        # Look for the specific PDF file
                        if filename == "RPA_aflevering_til_postkasse.pdf":
                            logger.info(f"Found target PDF: {filename}")
                            extracted_data['pdf_path'] = temp_path
            
            workqueue.add_item(
                data=extracted_data,
                reference=extracted_data.get('cpr_nr', 'unknown')
            )
            logger.info("-" * 80)
            
            # TODO: Add items to workqueue based on email content
            # workqueue.add_item(message, reference=message['id'])
            
    except Exception as e:
        logger.error(f"Error checking inbox: {e}")




async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict

            # Opret aktivitet i DUBU
            oprettet_aktivitet = dubu.aktiviteter.opret_aktivitet(
                sags_id=606094, # TEST_TESTESEN. Skal replaces på et tidspunkt
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
                sags_id=606094,
                dokument_titel="RPA Aflevering til postkasse" ,
                filnavn="RPA_aflevering_til_postkasse.pdf",
                dokument=upload_bytes,
                aktivitet=oprettet_aktivitet
            )

            print("howdy")
            # fjern temp fil:
            os.remove(data['pdf_path'])
 
            try:
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
    user_credential = Credential.get_credential("RoboA")

    tracker = Tracker(
        username=tracking_credential.username, 
        password=tracking_credential.password
    )

    dubu = DubuClientManager(
        username=f"{user_credential.username}@odense.dk",
        password=user_credential.password,
        idp=user_credential.data["idp"]
    )
    
    return tracker, dubu, ats


async def main(tracker, dubu, ats):
    """Main entry point."""
    logger = logging.getLogger(__name__)
    
    logger.info(f"Starting: {proces_navn}")
    
    global mail_service
    
    workqueue = ats.workqueue()
    
    # Queue management
    if "--queue" in sys.argv:
        # Initialize mail service (async)
        mail_service = MailService(settings)
        await mail_service.initialize()
        logger.info("Mail service initialized successfully")
        
        workqueue.clear_workqueue("new")
        await populate_queue(workqueue)
        exit(0)

    # Process workqueue
    await process_workqueue(workqueue)


if __name__ == "__main__":
    # Setup logging FIRST
    setup_logging()
    
    # Initialize sync services BEFORE starting asyncio
    tracker, dubu, ats = initialize_sync_services()
    
    # Now run async code
    asyncio.run(main(tracker, dubu, ats))
