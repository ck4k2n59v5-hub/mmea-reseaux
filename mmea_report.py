"""
Rapport quotidien des réseaux sociaux MMEA (Facebook + Instagram).

Récupère via l'API Meta (Graph API) :
  * le nombre d'abonnés Facebook et Instagram,
  * les likes / réactions sur les publications récentes,
  * les nouveaux commentaires depuis le dernier passage (et s'ils ont déjà une réponse de MMEA).

Compare avec l'état de la veille (state.json), puis envoie un email brut
avec le sujet "[MMEA-STATS] AAAA-MM-JJ". Claude lit ensuite cet email pour
rédiger le rapport final et les propositions de réponse.

Variables d'environnement (secrets GitHub) :
  META_PAGE_TOKEN     jeton d'accès de la page Facebook MMEA (sans expiration)
  FB_PAGE_ID          identifiant de la page Facebook
  IG_USER_ID          identifiant du compte Instagram Business
  GMAIL_ADDRESS       adresse Gmail qui envoie l'email
  GMAIL_APP_PASSWORD  mot de passe d'application Gmail (16 caractères)
  REPORT_TO           destinataire (par défaut : GMAIL_ADDRESS)
  GRAPH_VERSION       facultatif, version de l'API (par défaut v26.0)
  DRY_RUN=1           facultatif, affiche l'email au lieu de l'envoyer
"""

import datetime as dt
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

import requests

STATE_FILE = Path(__file__).with_name("state.json")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION") or "v26.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
POSTS_TO_TRACK = 25
TZ_CH = dt.timezone(dt.timedelta(hours=1))  # affichage approximatif heure suisse


# --------------------------------------------------------------------------
# Accès API
# --------------------------------------------------------------------------

def graph_get(path, params=None):
    token = os.environ["META_PAGE_TOKEN"]
    params = dict(params or {})
    resp = requests.get(
        f"{GRAPH}/{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code != 200:
        # On n'affiche jamais l'URL complète ni le jeton dans les logs
        try:
            err = resp.json().get("error", {})
        except ValueError:
            err = {"message": resp.text[:300]}
        raise RuntimeError(f"Erreur API Meta sur /{path.split('?')[0]} : "
                           f"{err.get('message')} (code {err.get('code')})")
    return resp.json()


def parse_time(value):
    # Meta renvoie "2026-11-24T08:15:00+0000"
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")


# --------------------------------------------------------------------------
# Facebook
# --------------------------------------------------------------------------

def fetch_facebook(page_id):
    page = graph_get(page_id, {"fields": "name,followers_count,fan_count"})
    posts = graph_get(f"{page_id}/posts", {
        "limit": POSTS_TO_TRACK,
        "fields": (
            "id,message,created_time,permalink_url,"
            "reactions.summary(total_count).limit(0),"
            "comments.limit(50).order(reverse_chronological).summary(total_count)"
            "{id,message,created_time,from,comments.limit(10){from}}"
        ),
    }).get("data", [])

    result = {
        "name": page.get("name"),
        "followers": page.get("followers_count"),
        "fans": page.get("fan_count"),
        "posts": {},
        "comments": [],
    }
    for p in posts:
        result["posts"][p["id"]] = {
            "likes": p.get("reactions", {}).get("summary", {}).get("total_count", 0),
            "created": p.get("created_time"),
            "text": (p.get("message") or "")[:120],
            "link": p.get("permalink_url"),
        }
        for c in p.get("comments", {}).get("data", []):
            author = (c.get("from") or {})
            replies = c.get("comments", {}).get("data", [])
            page_replied = any((r.get("from") or {}).get("id") == page_id for r in replies)
            if author.get("id") == page_id:
                continue  # commentaire écrit par MMEA elle-même
            result["comments"].append({
                "id": c["id"],
                "created": c.get("created_time"),
                "author": author.get("name", "(nom masqué par Meta)"),
                "text": c.get("message", ""),
                "post_text": (p.get("message") or "")[:120],
                "post_link": p.get("permalink_url"),
                "mmea_a_repondu": page_replied,
            })
    return result


# --------------------------------------------------------------------------
# Instagram
# --------------------------------------------------------------------------

def fetch_instagram(ig_id):
    user = graph_get(ig_id, {"fields": "username,followers_count,media_count"})
    username = user.get("username")
    media = graph_get(f"{ig_id}/media", {
        "limit": POSTS_TO_TRACK,
        "fields": (
            "id,caption,timestamp,permalink,like_count,comments_count,"
            "comments.limit(50){id,text,username,timestamp,replies{username}}"
        ),
    }).get("data", [])

    result = {
        "username": username,
        "followers": user.get("followers_count"),
        "posts": {},
        "comments": [],
    }
    for m in media:
        result["posts"][m["id"]] = {
            "likes": m.get("like_count", 0),
            "created": m.get("timestamp"),
            "text": (m.get("caption") or "")[:120],
            "link": m.get("permalink"),
        }
        for c in m.get("comments", {}).get("data", []):
            if c.get("username") == username:
                continue
            replies = c.get("replies", {}).get("data", [])
            result["comments"].append({
                "id": c["id"],
                "created": c.get("timestamp"),
                "author": c.get("username"),
                "text": c.get("text", ""),
                "post_text": (m.get("caption") or "")[:120],
                "post_link": m.get("permalink"),
                "mmea_a_repondu": any(r.get("username") == username for r in replies),
            })
    return result


# --------------------------------------------------------------------------
# Comparaison avec la veille
# --------------------------------------------------------------------------

def new_likes(now_posts, prev_posts, since):
    total = 0
    for pid, p in now_posts.items():
        if pid in prev_posts:
            total += max(0, p["likes"] - prev_posts[pid]["likes"])
        elif since is None or (p.get("created") and parse_time(p["created"]) > since):
            total += p["likes"]  # publication parue depuis le dernier passage
    return total


def diff(now, prev, since):
    if now is None:
        return None
    prev = prev or {}
    first_run = not prev
    out = {
        "abonnes": now["followers"],
        "nouveaux_abonnes": None if first_run or prev.get("followers") is None
        else now["followers"] - prev["followers"],
        "nouveaux_likes": None if first_run else new_likes(now["posts"], prev.get("posts", {}), since),
    }
    cutoff = since or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
    out["nouveaux_commentaires"] = sorted(
        [c for c in now["comments"] if c.get("created") and parse_time(c["created"]) > cutoff],
        key=lambda c: c["created"],
    )
    out["commentaires_sans_reponse"] = [
        c for c in now["comments"] if not c["mmea_a_repondu"]
    ]
    return out


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

def fmt_num(v, signed=False):
    if v is None:
        return "n/d (premier passage)"
    return f"{v:+d}" if signed else str(v)


def build_text(report):
    lines = [f"Rapport brut MMEA du {report['date']}", ""]
    for key, label in (("facebook", "FACEBOOK"), ("instagram", "INSTAGRAM")):
        d = report.get(key)
        if d is None:
            lines += [f"{label} : non configuré", ""]
            continue
        if "erreur" in d:
            lines += [f"{label} : ERREUR, {d['erreur']}", ""]
            continue
        lines += [
            label,
            f"  Abonnés : {d['abonnes']}"
            + ("" if d["nouveaux_abonnes"] is None else f" ({d['nouveaux_abonnes']:+d})"),
            f"  Nouveaux likes : {fmt_num(d['nouveaux_likes'])}",
            f"  Nouveaux commentaires : {len(d['nouveaux_commentaires'])}",
        ]
        for c in d["nouveaux_commentaires"]:
            statut = "répondu" if c["mmea_a_repondu"] else "SANS RÉPONSE"
            lines.append(f"    [{statut}] {c['author']} : {c['text']}")
            lines.append(f"      sur : {c['post_text'][:60]}  {c['post_link'] or ''}")
        lines.append("")
    lines += ["", "=== DONNÉES JSON (pour Claude) ===", json.dumps(report, ensure_ascii=False, indent=1)]
    return "\n".join(lines)


def send_email(subject, body):
    sender = os.environ["GMAIL_ADDRESS"]
    to = os.environ.get("REPORT_TO") or sender
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, os.environ["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    since = parse_time(state["last_run"]) if state.get("last_run") else None
    now_utc = dt.datetime.now(dt.timezone.utc)

    snapshots, report = {}, {"date": now_utc.astimezone(TZ_CH).strftime("%Y-%m-%d")}
    sources = (
        ("facebook", os.environ.get("FB_PAGE_ID"), fetch_facebook),
        ("instagram", os.environ.get("IG_USER_ID"), fetch_instagram),
    )
    errors = 0
    for key, obj_id, fetch in sources:
        if not obj_id:
            report[key] = None
            continue
        try:
            snap = fetch(obj_id)
        except Exception as exc:  # on continue avec l'autre réseau
            errors += 1
            report[key] = {"erreur": str(exc)}
            snapshots[key] = state.get(key)  # on garde l'ancien état
            continue
        snapshots[key] = {"followers": snap["followers"], "posts": snap["posts"]}
        report[key] = diff(snap, state.get(key), since)

    subject = f"[MMEA-STATS] {report['date']}"
    body = build_text(report)

    if os.environ.get("DRY_RUN") == "1":
        print(subject)
        print(body)
    else:
        send_email(subject, body)
        print("Email envoyé :", subject)

    snapshots["last_run"] = now_utc.strftime("%Y-%m-%dT%H:%M:%S+0000")
    STATE_FILE.write_text(json.dumps(snapshots, ensure_ascii=False, indent=1))

    if errors and errors == sum(1 for _, i, _ in sources if i):
        sys.exit(1)  # tout a échoué : GitHub t'envoie une alerte


if __name__ == "__main__":
    main()
