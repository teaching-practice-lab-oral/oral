import html
import logging
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import aiosmtplib

from app.config import settings

_mail_config: "SMTPConfig | None" = None
_signature_html: str | None = None
logger = logging.getLogger(__name__)

_SIGNATURE_PATH = Path(__file__).with_name("email_signature.html")
_BRAND = "AI 英語面試練習系統"
_FONT = "'Microsoft JhengHei','微軟正黑體',Arial,sans-serif"
_PRIMARY = "#4f46e5"


@dataclass(frozen=True)
class SMTPConfig:
    username: str
    password: str
    from_address: str
    from_name: str
    hostname: str
    port: int
    start_tls: bool
    use_tls: bool


@dataclass(frozen=True)
class MailMessage:
    subject: str
    recipients: list[str]
    body: str
    headers: dict[str, str]


def _cred_card(rows: list[tuple[str, str]]) -> str:
    """Render an email-client-safe detail card.

    Labels and values deliberately use separate lines.  A two-column table looks
    tidy on desktop, but mobile Gmail may enlarge CJK text and leave the value
    column only a few characters wide, causing IDs, dates, and addresses to wrap
    one character at a time.
    """
    cells = "".join(
        f'''<tr>
                    <td style="padding:12px 16px; border-bottom:{'0' if index == len(rows) - 1 else '1px solid #e5e7eb'};">
                        <div style="font-family:{_FONT}; font-size:13px; line-height:1.5; color:#6b7280;">{html.escape(label)}</div>
                        <div style="margin-top:3px; font-family:'Courier New',Consolas,monospace; font-size:16px; line-height:1.5; font-weight:700; color:#111827; overflow-wrap:anywhere; word-break:break-word;">{html.escape(value)}</div>
                    </td>
                </tr>'''
        for index, (label, value) in enumerate(rows)
    )
    return f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; margin:4px 0;">
            {cells}
        </table>'''


def _cta_button(url: str, label: str) -> str:
    """A high-visibility, email-client-safe button (padding on the <td> so it stays
    filled even in Outlook desktop, which ignores anchor padding/border-radius)."""
    return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px auto;">
            <tr>
                <td align="center" bgcolor="{_PRIMARY}" style="border-radius:8px; padding:15px 40px;">
                    <a href="{html.escape(url, quote=True)}" target="_blank" style="font-family:{_FONT}; font-size:16px; font-weight:700; color:#ffffff; text-decoration:none; display:inline-block;">{html.escape(label)} &rarr;</a>
                </td>
            </tr>
        </table>'''


def _login_url() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/"


def _email_shell(*, preheader: str, heading: str, name: str, body_inner: str) -> str:
    """Wrap message content in the shared branded layout (header band + card + signature)."""
    return f'''<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
<style>
    body, table, td, div, p, a {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    table, td {{ border-collapse:separate; }}
    @media only screen and (max-width:620px) {{
        .email-outer {{ padding:12px 6px !important; }}
        .email-header {{ padding:22px 20px !important; }}
        .email-content {{ padding:24px 20px !important; }}
        .email-signature {{ padding:0 20px 24px !important; }}
    }}
</style>
</head>
<body style="margin:0; padding:0; background-color:#f4f5f7;">
    <span style="display:none; max-height:0; overflow:hidden; opacity:0; color:#f4f5f7;">{html.escape(preheader)}</span>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="email-outer" style="background-color:#f4f5f7; padding:24px 12px;">
        <tr><td align="center">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px; background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,0.08);">
                <tr>
                    <td class="email-header" style="background-color:{_PRIMARY}; padding:28px 32px;">
                        <div style="font-family:{_FONT}; font-size:20px; font-weight:700; color:#ffffff;">{_BRAND}</div>
                        <div style="font-family:{_FONT}; font-size:13px; color:#c7d2fe; margin-top:4px;">{html.escape(heading)}</div>
                    </td>
                </tr>
                <tr>
                    <td class="email-content" style="padding:32px; font-family:{_FONT}; font-size:15px; line-height:1.7; color:#1f2937;">
                        <p style="margin:0 0 16px;">親愛的 <strong>{html.escape(name)}</strong> 同學，您好：</p>
                        {body_inner}
                    </td>
                </tr>
                <tr>
                    <td class="email-signature" style="padding:0 32px 32px;">{_get_signature()}</td>
                </tr>
            </table>
            <div style="font-family:{_FONT}; font-size:11px; color:#9ca3af; margin-top:16px;">本郵件由系統自動發送。</div>
        </td></tr>
    </table>
</body>
</html>'''


def _get_signature() -> str:
    global _signature_html
    if _signature_html is None:
        if settings.MAIL_SIGNATURE_HTML:
            _signature_html = settings.MAIL_SIGNATURE_HTML
        elif _SIGNATURE_PATH.exists():
            _signature_html = _SIGNATURE_PATH.read_text(encoding="utf-8")
        else:
            _signature_html = ""
    return _signature_html


def _get_mail_config() -> SMTPConfig:
    global _mail_config
    if _mail_config is None:
        username = settings.MAIL_USER or settings.MAIL_USERNAME
        mail_server = settings.MAIL_HOST or settings.MAIL_SERVER
        from_name = settings.MAIL_FROM_NAME or username
        _mail_config = SMTPConfig(
            username=username,
            password=settings.MAIL_PASSWORD,
            from_address=settings.MAIL_FROM,
            from_name=from_name,
            hostname=mail_server,
            port=settings.MAIL_PORT,
            start_tls=settings.MAIL_STARTTLS,
            use_tls=settings.MAIL_SSL_TLS,
        )
    return _mail_config


async def _send_message(message: MailMessage, conf: SMTPConfig | None = None) -> None:
    """Build a MIME message and use aiosmtplib's safe ``send_message`` path.

    Keeping SMTP commands inside aiosmtplib 5.x removes the vulnerable 2.x
    dependency previously pulled in by the old fastapi-mail wrapper.
    """
    conf = conf or _get_mail_config()
    mime = EmailMessage()
    mime["Subject"] = message.subject
    mime["From"] = formataddr((conf.from_name, conf.from_address))
    mime["To"] = ", ".join(message.recipients)
    for key, value in message.headers.items():
        mime[key] = value
    mime.set_content("此信件包含 HTML 內容，請使用支援 HTML 的郵件程式開啟。")
    mime.add_alternative(message.body, subtype="html")
    await aiosmtplib.send(
        mime,
        hostname=conf.hostname,
        port=conf.port,
        username=conf.username or None,
        password=conf.password or None,
        start_tls=conf.start_tls,
        use_tls=conf.use_tls,
        timeout=30,
    )


def _reply_to_headers() -> dict[str, str]:
    """Build a MIME-safe Reply-To header, including its display name."""
    address = settings.MAIL_REPLY_TO.strip()
    if not address:
        return {}
    name = settings.MAIL_REPLY_TO_NAME.strip()
    return {"Reply-To": formataddr((name, address)) if name else address}


def student_recipients(email: str, backup_email: str | None = None) -> list[str]:
    """Return the student's usable mailboxes, preserving order and removing duplicates."""
    recipients: list[str] = []
    seen: set[str] = set()
    for address in (email, backup_email):
        normalized = (address or "").strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            recipients.append(normalized)
            seen.add(key)
    return recipients


async def _send_student_message(
    *,
    subject: str,
    recipients: list[str],
    body: str,
) -> dict[str, bool]:
    """Send to every mailbox and succeed when at least one copy is delivered.

    Retrying the whole logical message after a partial delivery would send
    duplicates to the mailbox that already succeeded.  Callers therefore only
    receive an exception when every usable address failed.
    """
    conf = _get_mail_config()
    if not recipients:
        raise RuntimeError("No usable student email recipients")
    failures: list[tuple[str, Exception]] = []
    delivery: dict[str, bool] = {}
    for recipient in recipients:
        message = MailMessage(
            subject=subject,
            recipients=[recipient],
            body=body,
            headers=_reply_to_headers(),
        )
        try:
            await _send_message(message, conf)
            delivery[recipient] = True
        except Exception as exc:
            delivery[recipient] = False
            failures.append((recipient, exc))
    if failures and len(failures) == len(recipients):
        failed_addresses = ", ".join(address for address, _ in failures)
        raise RuntimeError(f"Failed to send email to: {failed_addresses}") from failures[0][1]
    if failures:
        logger.warning(
            "Student email was delivered partially; failed recipients=%s",
            ", ".join(address for address, _ in failures),
        )
    return delivery


async def send_password_email(
    email: str,
    name: str,
    student_id: str,
    password: str,
    backup_email: str | None = None,
) -> None:
    body_inner = f'''<p style="margin:0 0 14px;">您的 <strong>{_BRAND}</strong> 帳號已建立完成，以下是您的登入資訊：</p>
                        {_cred_card([("學號", student_id), ("初始密碼", password)])}
                        {_cta_button(_login_url(), "立即登入更改密碼")}
                        <p style="margin:18px 0 0; font-size:14px; color:#6b7280;">為了帳號安全，請於首次登入後盡快修改密碼。若有任何問題，歡迎直接回覆本郵件。</p>'''
    html_body = _email_shell(
        preheader="您的帳號已建立完成，請登入並修改密碼。",
        heading="帳號建立通知",
        name=name,
        body_inner=body_inner,
    )
    await _send_student_message(
        subject="AI 英語面試練習系統 — 帳號建立通知",
        recipients=student_recipients(email, backup_email),
        body=html_body,
    )


async def send_reset_password_email(
    email: str,
    name: str,
    new_password: str,
    backup_email: str | None = None,
) -> None:
    body_inner = f'''<p style="margin:0 0 14px;">您在 <strong>{_BRAND}</strong> 的密碼已由管理員重設，新的登入密碼如下：</p>
                        {_cred_card([("新密碼", new_password)])}
                        {_cta_button(_login_url(), "立即登入更改密碼")}
                        <p style="margin:18px 0 0; font-size:14px; color:#6b7280;">為了帳號安全，請於登入後立即修改密碼。若您並未申請重設密碼，請立即聯繫任課教師。</p>'''
    html_body = _email_shell(
        preheader="您的密碼已由管理員重設，請登入並修改密碼。",
        heading="密碼重設通知",
        name=name,
        body_inner=body_inner,
    )
    await _send_student_message(
        subject="AI 英語面試練習系統 — 密碼重設通知",
        recipients=student_recipients(email, backup_email),
        body=html_body,
    )


async def send_password_reset_link(
    email: str,
    name: str,
    reset_url: str,
    requested_backup_email: str | None = None,
    show_requested_backup_email: bool = False,
) -> None:
    conf = _get_mail_config()
    backup_email_check = ""
    if show_requested_backup_email:
        backup_email_check = f'''<p style="margin:18px 0 8px; font-size:14px; color:#374151;">您在申請時填寫的備用信箱如下，請確認是否正確：</p>
                        {_cred_card([("您填寫的備用信箱", requested_backup_email or "未提供")])}'''
    body_inner = f'''<p style="margin:0 0 14px;">我們收到您重設 <strong>{_BRAND}</strong> 密碼的申請。</p>
                        {_cta_button(reset_url, "設定新密碼")}
                        {backup_email_check}
                        <p style="margin:18px 0 0; font-size:14px; color:#6b7280;">此連結將於 {settings.PASSWORD_RESET_EXPIRE_HOURS} 小時後失效，且只能使用一次。若您未提出申請，請忽略本信並立即聯繫任課教師。</p>'''
    html_body = _email_shell(
        preheader=f"您的密碼重設連結有效期為 {settings.PASSWORD_RESET_EXPIRE_HOURS} 小時。",
        heading="密碼重設連結",
        name=name,
        body_inner=body_inner,
    )
    message = MailMessage(
        subject="AI 英語面試練習系統 — 密碼重設連結",
        recipients=[email],
        body=html_body,
        headers=_reply_to_headers(),
    )
    await _send_message(message, conf)


async def send_password_reset_admin_notice(
    name: str,
    student_id: str,
    course_num: str,
    requested_at: datetime,
    requested_backup_email: str | None,
) -> None:
    conf = _get_mail_config()
    admin_recipient = (settings.PASSWORD_RESET_ADMIN_EMAIL or settings.MAIL_REPLY_TO).strip()
    if not admin_recipient:
        raise RuntimeError("PASSWORD_RESET_ADMIN_EMAIL is not configured")
    rows = _cred_card([
        ("姓名", name),
        ("學號", student_id),
        ("課號", course_num),
        ("申請時間", requested_at.strftime("%Y/%m/%d %H:%M:%S")),
        ("學生填寫的備用信箱", requested_backup_email or "未提供"),
    ])
    body = f'''<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
<style>
    body, table, td, div, p, a {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    @media only screen and (max-width:620px) {{
        .email-outer {{ padding:12px 6px !important; }}
        .admin-content {{ padding:24px 20px !important; }}
    }}
</style>
</head>
<body style="margin:0; padding:0; background-color:#f4f5f7;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="email-outer" style="background-color:#f4f5f7; padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px; background-color:#ffffff; border-radius:12px;">
        <tr><td class="admin-content" style="padding:32px; font-family:{_FONT}; line-height:1.7; color:#1f2937;">
          <h2 style="margin:0 0 16px; color:#b91c1c; font-size:22px; line-height:1.4;">學生密碼重設申請通知</h2>
          <p style="margin:0 0 14px;">以下學生申請重設密碼，請密切注意：</p>
          {rows}
          <p style="font-size:14px; color:#6b7280; margin:18px 0;">若學生表示並未提出申請，請立即協助檢查帳號安全。通知信不包含密碼重設連結。</p>
          {_get_signature()}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>'''
    message = MailMessage(
        subject="學生密碼重設申請通知",
        recipients=[admin_recipient],
        body=body,
        headers=_reply_to_headers(),
    )
    await _send_message(message, conf)


async def send_reflection_issue_notice(
    email: str,
    student_name: str,
    student_id: str,
    assignment_title: str,
    issue_category: str,
    issue_description: str,
    admin_url: str,
) -> None:
    """Notify the protected administrator about a submitted issue report.

    The photo is deliberately not attached; authorized staff open it from the
    grading workspace through a short-lived signed URL.
    """
    conf = _get_mail_config()
    rows = _cred_card([
        ("學生", f"{student_name}（{student_id}）"),
        ("作業", assignment_title),
        ("問題類別", issue_category),
        ("問題說明", issue_description),
    ])
    body = f'''<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px;background:#f4f5f7;font-family:{_FONT};color:#1f2937;">
  <table role="presentation" width="100%"><tr><td align="center">
    <table role="presentation" width="100%" style="max-width:600px;background:#fff;border-radius:12px;padding:32px;">
      <tr><td><h2 style="margin:0 0 16px;color:#b91c1c;">學生心得問題回報</h2>
      <p>學生已正式送出含問題回報的心得，請至管理端查看與處理。</p>
      {rows}{_cta_button(admin_url, "前往批改與查看問題")}
      <p style="font-size:13px;color:#6b7280;">基於隱私與安全，通知信不附上學生照片。</p>
      {_get_signature()}</td></tr>
    </table>
  </td></tr></table>
</body></html>'''
    message = MailMessage(
        subject=f"學生心得問題回報 — {assignment_title}",
        recipients=[email],
        body=body,
        headers=_reply_to_headers(),
    )
    await _send_message(message, conf)


async def send_assignment_reminder_email(
    email: str,
    name: str,
    assignment_title: str,
    due_date: datetime,
    hours_left: int | None = None,
    backup_email: str | None = None,
) -> None:
    """Remind a student to finish an assignment before its deadline."""
    due_str = due_date.strftime("%Y/%m/%d %H:%M")
    rows = [("作業名稱", assignment_title), ("截止時間", due_str)]
    if hours_left is not None:
        rows.append(("剩餘時間", f"約 {hours_left} 小時"))
    body_inner = f'''<p style="margin:0 0 14px;">提醒您，以下 <strong>{_BRAND}</strong> 作業即將截止，請把握時間盡快完成：</p>
                        {_cred_card(rows)}
                        <p style="margin:14px 0 0; font-size:15px; color:#1f2937;">逾期將可能無法繳交或影響成績，請於截止前完成所有練習階段。</p>
                        {_cta_button(_login_url(), "立即登入完成作業")}
                        <p style="margin:18px 0 0; font-size:14px; color:#6b7280;">若您已完成此作業，請忽略本提醒。有任何問題歡迎直接回覆本郵件。</p>'''
    html_body = _email_shell(
        preheader=f"作業「{assignment_title}」即將於 {due_str} 截止，請盡快完成。",
        heading="作業截止提醒",
        name=name,
        body_inner=body_inner,
    )
    await _send_student_message(
        subject=f"AI 英語面試練習系統 — 作業即將截止：{assignment_title}",
        recipients=student_recipients(email, backup_email),
        body=html_body,
    )


async def send_late_deadline_email(
    email: str,
    name: str,
    assignment_title: str,
    late_deadline: datetime,
    backup_email: str | None = None,
) -> None:
    """Notify a student that a makeup submission window has been opened."""
    deadline_str = late_deadline.strftime("%Y/%m/%d %H:%M")
    body_inner = f'''<p style="margin:0 0 14px;">老師已為您開放以下 <strong>{_BRAND}</strong> 作業的補繳期限：</p>
                        {_cred_card([("作業名稱", assignment_title), ("補繳截止時間", deadline_str)])}
                        <p style="margin:14px 0 0; font-size:15px; color:#1f2937;">請於補繳截止時間前完成所有練習階段並提交；逾期後作業將恢復為唯讀狀態。</p>
                        {_cta_button(_login_url(), "立即登入完成補繳")}
                        <p style="margin:18px 0 0; font-size:14px; color:#6b7280;">若您對補繳安排有疑問，歡迎直接回覆本郵件聯繫任課教師。</p>'''
    html_body = _email_shell(
        preheader=f"作業「{assignment_title}」已開放補繳，截止時間為 {deadline_str}。",
        heading="作業補繳通知",
        name=name,
        body_inner=body_inner,
    )
    await _send_student_message(
        subject=f"AI 英語面試練習系統 — 作業補繳通知：{assignment_title}",
        recipients=student_recipients(email, backup_email),
        body=html_body,
    )
