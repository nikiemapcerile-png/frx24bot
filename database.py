"""
database.py — Base de données SQLite locale
"""
import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
DB_PATH = os.environ.get("DB_PATH", "/data/frx24bot.db")

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS matches (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id    TEXT UNIQUE,
        league      TEXT,
        team1       TEXT,
        team2       TEXT,
        score1      INTEGER DEFAULT 0,
        score2      INTEGER DEFAULT 0,
        score1_ht   INTEGER DEFAULT 0,
        score2_ht   INTEGER DEFAULT 0,
        status      INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now')),
        finished_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_teams  ON matches(team1, team2);
    CREATE INDEX IF NOT EXISTS idx_league ON matches(league);
    """)
    conn.commit()
    conn.close()

def save_match(match_id, league, team1, team2,
               score1=0, score2=0, score1_ht=0, score2_ht=0, finished=False):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO matches
                (match_id, league, team1, team2, score1, score2,
                 score1_ht, score2_ht, status, finished_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                score1=excluded.score1, score2=excluded.score2,
                score1_ht=excluded.score1_ht, score2_ht=excluded.score2_ht,
                status=excluded.status, finished_at=excluded.finished_at
        """, (
            match_id, league, team1, team2,
            score1, score2, score1_ht, score2_ht,
            1 if finished else 0,
            datetime.now().isoformat() if finished else None
        ))
        conn.commit()
    finally:
        conn.close()

def get_h2h(team1, team2, limit=5):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT team1, team2, score1, score2, score1_ht, score2_ht, finished_at
            FROM matches
            WHERE status=1
              AND ((team1=? AND team2=?) OR (team1=? AND team2=?))
            ORDER BY finished_at DESC LIMIT ?
        """, (team1, team2, team2, team1, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_team_stats(team, league=None, limit=20):
    conn = get_conn()
    try:
        if league:
            rows = conn.execute("""
                SELECT team1, team2, score1, score2, score1_ht, score2_ht
                FROM matches WHERE status=1 AND league=?
                  AND (team1=? OR team2=?)
                ORDER BY finished_at DESC LIMIT ?
            """, (league, team, team, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT team1, team2, score1, score2, score1_ht, score2_ht
                FROM matches WHERE status=1 AND (team1=? OR team2=?)
                ORDER BY finished_at DESC LIMIT ?
            """, (team, team, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def compute_team_stats(team, rows):
    if not rows:
        return None
    gs_ht=[];gs_2h=[];gc_ht=[];gc_2h=[]
    wins=draws=losses=0
    for r in rows:
        home = r["team1"]==team
        gh  = r["score1_ht"] if home else r["score2_ht"]
        gch = r["score2_ht"] if home else r["score1_ht"]
        gf  = r["score1"]    if home else r["score2"]
        gcf = r["score2"]    if home else r["score1"]
        g2  = gf - gh
        gc2 = gcf - gch
        gs_ht.append(gh); gs_2h.append(g2)
        gc_ht.append(gch); gc_2h.append(gc2)
        if gf>gcf: wins+=1
        elif gf==gcf: draws+=1
        else: losses+=1
    n=len(rows)
    return {
        "matches": n, "wins": wins, "draws": draws, "losses": losses,
        "avg_scored_ht":   round(sum(gs_ht)/n,2),
        "avg_scored_2h":   round(sum(gs_2h)/n,2),
        "avg_conceded_ht": round(sum(gc_ht)/n,2),
        "avg_conceded_2h": round(sum(gc_2h)/n,2),
        "avg_goals_ht":    round((sum(gs_ht)+sum(gc_ht))/n,2),
        "avg_goals_2h":    round((sum(gs_2h)+sum(gc_2h))/n,2),
    }

init_db()
