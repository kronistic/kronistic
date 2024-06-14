from smtplib import SMTP, SMTP_SSL, ssl
from email.message import EmailMessage
from email.utils import make_msgid
from kron_app import app

def get_mailer(env=app.config['ENV']):
    sender = 'Kronistic <no-reply@kronistic.com>'
    if env == 'production':
        return Gmailer(sender, app.config['SMTP_LOGIN'], app.config['SMTP_PASSWORD'])
    else:
        #return DebugMailer(sender)
        return LoggingMailer(sender)

def sendmail(m):
    get_mailer().send(*m)

def message(sender, recipients, subject, body):
    msg = EmailMessage()
    msg.set_content(body)
    msg['From'] = sender
    msg['To'] = recipients
    msg['Subject'] = subject
    msg['Message-ID'] = make_msgid(domain=app.config['HOSTNAME'])
    return msg

# Run local debug smtp server with:
# python -m smtpd -c DebuggingServer -n localhost:1025
class DebugMailer():
    def __init__(self, sender):
        self.sender = sender
    def send(self, recipients, subject, body):
        with SMTP('localhost', port=1025) as smtp:
            msg = message(self.sender, recipients, subject, body)
            smtp.send_message(msg)

class LoggingMailer():
    def __init__(self, sender):
        self.sender = sender
    def send(self, recipients, subject, body):
        s = '=' * 72
        print(s)
        print(message(self.sender, recipients, subject, body))
        print(s)

class Gmailer():
    def __init__(self, sender, login, password):
        self.sender = sender
        self.login = login
        self.password = password
    def send(self, recipients, subject, body):
        context = ssl.create_default_context()
        msg = message(self.sender, recipients, subject, body)
        with SMTP_SSL('smtp-relay.gmail.com', port=465, context=context) as smtp:
            smtp.login(self.login, self.password)
            smtp.send_message(msg)
