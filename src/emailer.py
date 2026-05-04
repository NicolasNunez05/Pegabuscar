import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from config import EMAIL_SENDER, EMAIL_RECEIVER

SCORE_COLOR = {
    range(80, 101): ("#16a34a", "🔥 Excelente match"),
    range(60, 80):  ("#2563eb", "✅ Buen match"),
    range(40, 60):  ("#d97706", "⚡ Match parcial"),
    range(0, 40):   ("#6b7280", "🔎 Revisar"),
}


def _score_label(score: int):
    for rng, value in SCORE_COLOR.items():
        if score in rng:
            return value
    return "#6b7280", "🔎 Revisar"


def _job_card(job: dict) -> str:
    score = job.get("score", 0)
    color, label = _score_label(score)
    skills = ", ".join(job.get("matched_skills", [])[:8]) or "—"
    pub = job.get("published_at")
    pub_str = pub.strftime("%d/%m %H:%M UTC") if pub else "Fecha desconocida"
    source_badge = f'<span style="background:#f3f4f6;color:#374151;padding:2px 8px;border-radius:12px;font-size:12px;">{job["source"]}</span>'
    return f"""
    <div style="border:1px solid #e5e7eb;border-radius:10px;padding:16px 20px;
                margin-bottom:14px;background:#ffffff;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
        <div>
          <a href="{job['url']}" style="font-size:17px;font-weight:700;color:#111827;text-decoration:none;">
            {job['title']}
          </a>
          <div style="margin-top:4px;color:#6b7280;font-size:14px;">
            {job.get('company','—')} · {job.get('location','—')} · {pub_str}
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:26px;font-weight:800;color:{color};">{score}%</div>
          <div style="font-size:12px;color:{color};font-weight:600;">{label}</div>
        </div>
      </div>
      <div style="margin-top:10px;font-size:13px;color:#374151;">
        <strong>Skills detectados:</strong> {skills}
      </div>
      <div style="margin-top:8px;">{source_badge}</div>
      <div style="margin-top:12px;">
        <a href="{job['url']}"
           style="background:#111827;color:#ffffff;padding:8px 18px;border-radius:7px;
                  text-decoration:none;font-size:14px;font-weight:600;">
          Ver oferta →
        </a>
      </div>
    </div>
    """


def build_html(jobs: list[dict], total_scraped: int) -> str:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    count = len(jobs)
    if count == 0:
        body = """
        <div style="text-align:center;padding:48px 24px;color:#6b7280;">
          <div style="font-size:48px;">🔍</div>
          <p style="font-size:18px;margin-top:12px;">Sin ofertas nuevas esta hora.</p>
          <p style="font-size:14px;">El sistema sigue corriendo.</p>
        </div>
        """
    else:
        cards = "\n".join(_job_card(j) for j in jobs)
        body = f"""
        <div style="margin-bottom:20px;padding:14px 18px;background:#f0fdf4;
                    border-radius:8px;border-left:4px solid #16a34a;font-size:15px;color:#166534;">
          <strong>{count} oferta(s) nueva(s)</strong> de {total_scraped} revisadas esta hora.
        </div>
        {cards}
        """
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:680px;margin:32px auto;padding:0 16px 48px;">
    <div style="background:#111827;border-radius:12px 12px 0 0;padding:24px 28px;color:#ffffff;">
      <div style="font-size:22px;font-weight:800;">🎯 Pegabuscar — Nicolás</div>
      <div style="font-size:13px;color:#9ca3af;margin-top:4px;">Reporte hourly · {now}</div>
    </div>
    <div style="background:#f9fafb;padding:24px 28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;">
      {body}
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
      <p style="font-size:12px;color:#9ca3af;text-align:center;">
        Pegabuscar · GitHub Actions · Postulación manual.<br>
        Para ajustar filtros edita <code>src/config.py</code>.
      </p>
    </div>
  </div>
</body>
</html>"""


def send_email(jobs: list[dict], total_scraped: int):
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not password:
        print("⚠️ GMAIL_APP_PASSWORD no configurada. Email no enviado.")
        return
    count = len(jobs)
    subject = (
        f"[Pegabuscar] {count} oferta(s) nueva(s) — {datetime.now(timezone.utc).strftime('%d/%m %H:%M')}"
        if count > 0
        else f"[Pegabuscar] Sin novedades — {datetime.now(timezone.utc).strftime('%d/%m %H:%M')}"
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(build_html(jobs, total_scraped), "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, password)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print(f"✅ Email enviado: {subject}")