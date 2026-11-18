#!/usr/bin/env python3
"""Prepare or send one grocery report per Belgrade date and recipient."""

import argparse
import hashlib
import html
import json
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "dist" / "data.json"
STATE_PATH = ROOT / ".mail-state.json"
SITE_URL = "https://bagavacluka-star.github.io/luca-grocery-dashboard/"
STORE_IDS = ("lidl", "metro", "maxi")
ITEM_NAMES = {
    "oil": "Suncokretovo ulje 1 l",
    "flour": "Brašno T-500 1 kg",
    "sugar": "Šećer kristal 1 kg",
    "eggs": "Jaja M 10 kom",
    "milk": "Mleko 2,8% 1 l",
}


def money(value):
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def label(row, item_id):
    if row["kind"] == "source_error":
        return f"izvor nedostupan ({row['reason']})"
    result = f"{money(row['price'])} RSD"
    if row["kind"] == "pack_alternative":
        basis = "RSD/10 kom" if item_id == "eggs" else "RSD/kg"
        result += f" ({row['pack']}; drugo pakovanje, {money(row['equivalent_price'])} {basis} preračunato)"
    elif row["kind"] == "spec_alternative":
        result += f" ({row['pack']}; druga specifikacija, van poređenja)"
    return result


def report(data, test=False):
    day = data["generated_at"][:10]
    date = datetime.fromisoformat(data["generated_at"]).strftime("%d.%m.%Y.")
    rows = [row for row in data["observations"] if row["date"] == day]
    if len(rows) != 15 or len({(r["item"], r["store"]) for r in rows}) != 15:
        raise ValueError("Dnevni izveštaj zahteva 15 jedinstvenih provera.")
    current = {(r["item"], r["store"]): r for r in rows}
    counts = {kind: sum(r["kind"] == kind for r in rows) for kind in ("exact", "pack_alternative", "spec_alternative", "source_error")}
    alternatives = counts["pack_alternative"] + counts["spec_alternative"]
    subject = f"{'[PROBA] ' if test else ''}Cene namirnica | {date}"

    lines = [
        "Zdravo,", "",
        f"Danas je provereno {counts['exact']} od 15 proizvoda sa tačnom specifikacijom. "
        f"{alternatives} su označene alternative; neuspelih provera: {counts['source_error']}.", "",
    ]
    table = []
    for item_id, item_name in ITEM_NAMES.items():
        offers = [label(current[(item_id, store_id)], item_id) for store_id in STORE_IDS]
        table.append((item_name, *offers))
        lines.append(item_name)
        for store_name, offer in zip(("Lidl", "Metro Zemun", "Maxi Online"), offers):
            lines.append(f"  {store_name}: {offer}")
        lines.append("")

    changes = []
    for row in rows:
        if row["price"] is None:
            continue
        previous = next((old for old in reversed(data["observations"])
                         if old["date"] < day and old["item"] == row["item"]
                         and old["store"] == row["store"] and old["price"] is not None), None)
        if previous and previous["price"] != row["price"]:
            changes.append(f"{ITEM_NAMES[row['item']]} / {row['store']}: "
                           f"{money(previous['price'])} → {money(row['price'])} RSD")
    lines += ["Promene cena istog praćenog proizvoda:"]
    lines += [f"- {change}" for change in changes] if changes else ["Nema promena u odnosu na prethodnu uspešnu proveru."]
    lines += ["", "Važne napomene: Lidl brašno je pakovanje od 2 kg, jaja od 24 komada, "
              "a Lidl mleko ima 3,2% masti umesto traženih 2,8%. Te alternative nisu tačni proizvodi.",
              "Dostupnost u konkretnoj radnji nije potvrđena.", "", f"Dashboard: {SITE_URL}", "", "Izvori:"]
    for item_id, item_name in ITEM_NAMES.items():
        for store_id, store_name in zip(STORE_IDS, ("Lidl", "Metro Zemun", "Maxi Online")):
            row = current[(item_id, store_id)]
            lines.append(f"- {item_name} / {store_name}: {row['source']}")
    plain = "\n".join(lines) + "\n"

    table_rows = "".join("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells) + "</tr>"
                         for cells in table)
    html_body = (
        "<!doctype html><html lang='sr'><meta charset='utf-8'><body>"
        f"<p>Zdravo,</p><p>{counts['exact']} od 15 tačnih proizvoda; {alternatives} alternative; "
        f"{counts['source_error']} neuspelih provera.</p>"
        "<table border='1' cellpadding='7' cellspacing='0'><thead><tr><th>Namirnica</th><th>Lidl</th>"
        "<th>Metro Zemun</th><th>Maxi Online</th></tr></thead><tbody>"
        f"{table_rows}</tbody></table>"
        "<h3>Promene cena istog praćenog proizvoda</h3><ul>"
        + "".join(f"<li>{html.escape(change)}</li>" for change in changes or ["Nema promena u odnosu na prethodnu uspešnu proveru."])
        + "</ul><p>Lidl brašno (2 kg), jaja (24 kom) i mleko (3,2%) su jasno označene alternative. "
        "Dostupnost u konkretnoj radnji nije potvrđena.</p>"
        f"<p><a href='{html.escape(SITE_URL)}'>Otvori dashboard sa izvorima</a></p>"
        "<h3>Izvori</h3><ul>"
        + "".join(f"<li>{html.escape(ITEM_NAMES[item_id])} / {html.escape(store_name)}: "
                  f"<a href='{html.escape(current[(item_id, store_id)]['source'])}'>proizvod</a></li>"
                  for item_id in ITEM_NAMES for store_id, store_name in zip(STORE_IDS, ("Lidl", "Metro Zemun", "Maxi Online")))
        + "</ul></body></html>"
    )
    return day, subject, plain, html_body


def address(value, name):
    parsed = parseaddr(value)[1]
    if parsed != value or "@" not in parsed or any(c.isspace() for c in parsed):
        raise ValueError(f"{name} nije ispravna email adresa.")
    return parsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Send through Gmail SMTP")
    parser.add_argument("--test", action="store_true", help="Mark the message as a test")
    args = parser.parse_args()
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    day, subject, plain, html_body = report(data, test=args.test)
    if not args.send:
        print(f"Subject: {subject}\n\n{plain}")
        return

    if day != datetime.now(ZoneInfo("Europe/Belgrade")).date().isoformat():
        raise RuntimeError("Podaci nisu provereni danas; email nije poslat.")
    sender = address(os.environ["GMAIL_USER"], "GMAIL_USER")
    recipient = address(os.environ["MAIL_TO"], "MAIL_TO")
    password = os.environ["GMAIL_APP_PASSWORD"]
    key = hashlib.sha256((password + "\0" + recipient.lower()).encode()).hexdigest()
    mode = "test" if args.test else "daily"
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"sent": []}
    if any(entry == {"date": day, "recipient_hash": key, "mode": mode} for entry in state["sent"]):
        print(f"SKIP: {mode} email je već poslat za {day} i ovog primaoca.")
        return

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(plain)
    message.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)

    state["sent"].append({"date": day, "recipient_hash": key, "mode": mode})
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"SENT: {mode} email za {day}; evidencija upisana.")


if __name__ == "__main__":
    main()
