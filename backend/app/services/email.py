# app/services/email.py
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")


def send_alert_email(
    asset_title: str,
    infringing_url: str,
    severity_label: str,
    confidence: float,
    match_type: str,
    platform: str | None,
    ai_reasoning: str | None,
    alert_id: str,
) -> bool:
    """Send alert notification email via Gmail SMTP. Returns True on success."""
    if not all([SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO]):
        logger.warning("Email not configured — skipping alert email.")
        return False

    subject = f"[{severity_label.upper()}] Copyright Alert: {asset_title}"

    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">🚨 Sports IP Protection Alert</h2>
        </div>
        <div style="background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; border: 1px solid #ddd;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px; font-weight: bold;">Asset</td>
                    <td style="padding: 8px;">{asset_title}</td></tr>
                <tr style="background: #fff;"><td style="padding: 8px; font-weight: bold;">Severity</td>
                    <td style="padding: 8px;">
                        <span style="background: {'#d32f2f' if severity_label == 'critical' else '#f57c00' if severity_label == 'high' else '#fbc02d' if severity_label == 'medium' else '#388e3c'}; 
                        color: white; padding: 2px 10px; border-radius: 4px; font-size: 12px;">
                        {severity_label.upper()}</span>
                    </td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Confidence</td>
                    <td style="padding: 8px;">{confidence * 100:.1f}%</td></tr>
                <tr style="background: #fff;"><td style="padding: 8px; font-weight: bold;">Match Type</td>
                    <td style="padding: 8px;">{match_type}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Platform</td>
                    <td style="padding: 8px;">{platform or "Unknown"}</td></tr>
                <tr style="background: #fff;"><td style="padding: 8px; font-weight: bold;">Infringing URL</td>
                    <td style="padding: 8px;"><a href="{infringing_url}">{infringing_url}</a></td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">AI Analysis</td>
                    <td style="padding: 8px;">{ai_reasoning or "N/A"}</td></tr>
            </table>
            <div style="margin-top: 20px; text-align: center;">
                <a href="http://localhost:8000/docs#/alerts" 
                   style="background: #1a1a2e; color: white; padding: 10px 24px; 
                   border-radius: 6px; text-decoration: none; font-weight: bold;">
                   View Alert & Initiate DMCA
                </a>
            </div>
            <p style="color: #888; font-size: 12px; margin-top: 16px;">Alert ID: {alert_id}</p>
        </div>
    </body></html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL_TO
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ALERT_EMAIL_TO, msg.as_string())

        logger.info("Alert email sent for alert_id=%s", alert_id)
        return True

    except Exception as exc:
        logger.error("Failed to send alert email: %s", exc)
        return False