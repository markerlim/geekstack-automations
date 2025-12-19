import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


class NotificationService:
    """Enhanced notification service with email capabilities"""

    def __init__(self):
        """Initialize notification service with email configuration"""
        self.smtp_server = os.getenv('SMTP_HOST','')
        self.smtp_port = int(os.getenv('SMTP_PORT',''))
        self.email_user = os.getenv('SMTP_USER', '')
        self.email_password = os.getenv('SMTP_PASSWORD', '')
        self.trello_email = os.getenv('TRELLO_EMAIL', '')
    
    def send_email_notification(self, subject: str, message: str, recipient: str = None) -> bool:
        """
        Send email notification to specified recipient or default Trello email
        
        Args:
            subject (str): Email subject line
            message (str): Email body content
            recipient (str): Recipient email (optional, defaults to Trello email)
        
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            if not self.email_user or not self.email_password:
                print("⚠️ Email credentials not configured. Check EMAIL_USER and EMAIL_PASSWORD environment variables.")
                return False
            
            recipient = recipient or self.trello_email
            
            # Create message
            msg = MimeMultipart()
            msg['From'] = self.email_user
            msg['To'] = recipient
            msg['Subject'] = subject
            
            # Add body to email
            msg.attach(MimeText(message, 'plain'))
            
            # Create SMTP session
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()  # Enable security
            server.login(self.email_user, self.email_password)
            
            # Send email
            text = msg.as_string()
            server.sendmail(self.email_user, recipient, text)
            server.quit()
            
            print(f"✅ Email sent successfully to {recipient}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            return False
    
    def notify_trello_new_actions(self, action_summary: str, details: list = None):
        """
        Send notification to Trello about new actions to take
        
        Args:
            action_summary (str): Brief summary of the actions needed
            details (list): Optional list of detailed action items
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"GeekStack Automations - New Actions Required ({timestamp})"
        
        # Build email body
        email_body = f"""
GeekStack Automations Update
=====================================

Timestamp: {timestamp}

Action Summary:
{action_summary}

"""
        
        if details:
            email_body += "Detailed Actions Required:\n"
            for i, detail in enumerate(details, 1):
                email_body += f"{i}. {detail}\n"
        
        email_body += """
=====================================
This notification was sent automatically by GeekStack Automations.
"""
        
        # Send email notification
        success = self.send_email_notification(subject, email_body)
        
        # Also send console notification
        self.send_notification(f"Trello notification: {action_summary}")
        
        return success

    def notify_scraping_complete(self, tcg_name: str, set_name: str, card_count: int, status: str = "success"):
        """
        Notify about completed scraping operations
        
        Args:
            tcg_name (str): Name of the TCG (e.g., "One Piece", "Dragon Ball Z")
            set_name (str): Set/booster name that was scraped
            card_count (int): Number of cards processed
            status (str): Status of the operation ("success", "partial", "failed")
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_emoji = "✅" if status == "success" else "⚠️" if status == "partial" else "❌"
        
        subject = f"Scraping Complete: {tcg_name} - {set_name} ({status_emoji})"
        
        email_body = f"""
GeekStack Automations - Scraping Report
=======================================

Timestamp: {timestamp}
Status: {status_emoji} {status.upper()}

TCG: {tcg_name}
Set: {set_name}
Cards Processed: {card_count}

Next Actions:
1. Review scraped data in MongoDB
2. Verify image uploads in GCS
3. Update frontend if needed
4. Check for any errors in logs

=======================================
This notification was sent automatically by GeekStack Automations.
"""
        
        return self.send_email_notification(subject, email_body)

