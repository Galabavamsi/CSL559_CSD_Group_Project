"""Sending email. One function, `send`, and two ways to carry it out, chosen by EMAIL_BACKEND:

* `log` (the default, for a laptop and the tests): nothing leaves the machine. The message is written to the log and
  kept in `outbox`, so a developer can read a login code and a test can check what would have been sent.
  Never use it on a server: it writes login codes to the log.
* `ses`: Amazon Simple Email Service, from the address EMAIL_FROM, whose domain must be verified in SES.

A failed send raises `EmailError`. Callers that send after answering the request (login codes do) log it and move
on: the person asks for another code.
"""
import logging
from collections import deque
from dataclasses import dataclass

from . import config

log = logging.getLogger("darkstore.email")


class EmailError(Exception):
    pass


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str


outbox: deque[Message] = deque(maxlen=50)        # the newest messages the `log` backend was asked to send


def _send_with_ses(message: Message) -> None:
    import boto3      # imported here: the `log` backend needs no AWS
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        boto3.client("sesv2", region_name=config.EMAIL_REGION or None).send_email(
            FromEmailAddress=config.EMAIL_FROM,
            Destination={"ToAddresses": [message.to]},
            Content={"Simple": {"Subject": {"Data": message.subject, "Charset": "UTF-8"},
                                "Body": {"Text": {"Data": message.text, "Charset": "UTF-8"}}}})
    except (BotoCoreError, ClientError) as error:
        # The error names the service and the reason, never the message: a login code must not reach the log.
        raise EmailError(f"Amazon SES refused or could not be reached: {type(error).__name__}") from error


def send(to: str, subject: str, text: str) -> None:
    """Send one plain-text email, or raise EmailError."""
    message = Message(to=to, subject=subject, text=text)
    if config.EMAIL_BACKEND == "ses":
        _send_with_ses(message)
    elif config.EMAIL_BACKEND == "log":
        outbox.append(message)
        log.warning("EMAIL_BACKEND=log, so nothing was sent. To: %s | %s | %s", to, subject, text.replace("\n", " "))
    else:
        raise EmailError(f"Unknown EMAIL_BACKEND {config.EMAIL_BACKEND!r}: use 'log' or 'ses'")


def send_quietly(to: str, subject: str, text: str) -> None:
    """`send`, for use after the request has been answered: a failure is logged, without the message, not raised."""
    try:
        send(to, subject, text)
    except EmailError as error:
        log.error("Could not send an email (%s)", error)
