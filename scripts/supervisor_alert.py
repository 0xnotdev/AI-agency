import sys
import os

# Add root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.alerts import send_telegram_alert

def main():
    while True:
        # Transition to READY state and wait for an event
        sys.stdout.write("READY\n")
        sys.stdout.flush()

        line = sys.stdin.readline()
        if not line:
            break

        headers = dict(x.split(':') for x in line.split())
        payload = sys.stdin.read(int(headers['len']))
        
        if headers.get('eventname') == 'PROCESS_STATE_FATAL':
            pdata = dict(x.split(':') for x in payload.split())
            process_name = pdata.get('processname', 'Unknown')
            
            alert_msg = (
                f"🚨 <b>FATAL CRASH</b>\n\n"
                f"<b>Process:</b> {process_name}\n"
                f"<b>Status:</b> Failed to restart after multiple attempts.\n"
                f"<b>Action Required:</b> Check application logs immediately."
            )
            
            try:
                send_telegram_alert(alert_msg)
            except Exception as e:
                sys.stderr.write(f"Failed to send telegram alert: {str(e)}\n")
                sys.stderr.flush()

        # Acknowledge the event
        sys.stdout.write("RESULT 2\nOK")
        sys.stdout.flush()

if __name__ == '__main__':
    main()
