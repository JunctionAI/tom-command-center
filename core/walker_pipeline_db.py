"""
Walker Capital Management — Pipeline Database
SQLite store for all companies moving through the 7-stage investment pipeline.
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "walker_pipeline.db"

STAGES = [
    "DISCOVERED",
    "SCREENED",
    "RESEARCHED",
    "VALUED",
    "RISK_ASSESSED",
    "SIMULATED",
    "DECISION_READY",
    "APPROVED",
    "WATCHING",
    "REJECTED",
]


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def initialise_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            exchange TEXT,
            sector TEXT,
            segment TEXT,           -- 'A' (mature) or 'B' (growth)
            stage TEXT NOT NULL DEFAULT 'DISCOVERED',
            catalyst_score INTEGER, -- 1=Weak, 2=Moderate, 3=Strong
            catalyst_description TEXT,
            discovery_thesis TEXT,
            conviction_score REAL,  -- 1-10
            added_date TEXT,
            updated_date TEXT,
            decision TEXT,
            decision_by TEXT,
            decision_date TEXT,
            decision_rationale TEXT,
            notes TEXT,
            UNIQUE(ticker, exchange)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS research_briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            brief_text TEXT,
            business_model TEXT,
            competitive_position TEXT,
            management_quality TEXT,
            industry_dynamics TEXT,
            catalyst_detail TEXT,
            bear_case TEXT,
            key_metrics TEXT,       -- JSON
            comparable_companies TEXT, -- JSON list
            created_at TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS valuations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            -- Scenario DCF
            dcf_bull REAL,
            dcf_base REAL,
            dcf_bear REAL,
            dcf_weighted REAL,
            dcf_wacc REAL,
            dcf_terminal_growth REAL,
            -- Comps
            comps_ev_ebitda REAL,
            comps_fwd_pe REAL,
            comps_ev_fcf REAL,
            comps_implied_value REAL,
            -- Morningstar
            ms_fair_value REAL,
            ms_moat TEXT,
            ms_stars INTEGER,
            ms_stewardship TEXT,
            -- Summary
            current_price REAL,
            weighted_intrinsic_value REAL,
            margin_of_safety REAL,
            valuation_confidence TEXT,
            sensitivity_table TEXT,  -- JSON
            created_at TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS risk_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            var_95 REAL,
            var_99 REAL,
            cvar_99 REAL,
            altman_z REAL,
            altman_zone TEXT,       -- SAFE, GREY, DISTRESS
            fcf_conversion REAL,
            earnings_quality_flags TEXT,  -- JSON list of flags
            fisher_score INTEGER,
            fisher_breakdown TEXT,        -- JSON {point: score}
            fisher_strengths TEXT,        -- JSON list
            fisher_concerns TEXT,         -- JSON list
            conviction_score REAL,
            created_at TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS simulations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            mirofish_project_id TEXT,
            mirofish_simulation_id TEXT,
            market_share_1yr TEXT,
            market_share_3yr TEXT,
            market_share_5yr TEXT,
            tam_current REAL,
            tam_1yr REAL,
            tam_3yr REAL,
            tam_5yr REAL,
            key_competitive_risk TEXT,
            bull_scenario TEXT,
            base_scenario TEXT,
            bear_scenario TEXT,
            simulation_confidence TEXT,
            full_report TEXT,
            created_at TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            decision TEXT NOT NULL,  -- BUY, WATCH, AVOID
            decision_by TEXT,
            rationale TEXT,
            entry_price REAL,
            target_price REAL,
            stop_loss REAL,
            position_size_pct REAL,
            monitoring_criteria TEXT,  -- JSON list
            created_at TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            reason TEXT,
            review_date TEXT,
            added_date TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Walker Capital pipeline DB initialised")


def add_company(ticker, name, exchange, sector, discovery_thesis, segment=None):
    """Add a newly discovered company. Returns company_id or None if already exists."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    try:
        c.execute("""
            INSERT INTO companies (ticker, name, exchange, sector, segment, stage, discovery_thesis, added_date, updated_date)
            VALUES (?, ?, ?, ?, ?, 'DISCOVERED', ?, ?, ?)
        """, (ticker.upper(), name, exchange, sector, segment, discovery_thesis, now, now))
        conn.commit()
        company_id = c.lastrowid
        logger.info(f"Added company {ticker} to pipeline (id={company_id})")
        return company_id
    except sqlite3.IntegrityError:
        logger.info(f"Company {ticker} already in pipeline — skipping")
        return None
    finally:
        conn.close()


def advance_stage(company_id, new_stage, notes=None):
    """Move company to next pipeline stage."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        UPDATE companies SET stage=?, updated_date=?, notes=? WHERE id=?
    """, (new_stage, now, notes, company_id))
    conn.commit()
    conn.close()
    logger.info(f"Company {company_id} advanced to {new_stage}")


def update_catalyst(company_id, catalyst_score, catalyst_description):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        UPDATE companies SET catalyst_score=?, catalyst_description=?, segment=?,
        updated_date=? WHERE id=?
    """, (catalyst_score, catalyst_description,
          'B' if catalyst_score else None, now, company_id))
    conn.commit()
    conn.close()


def save_research_brief(company_id, brief_data: dict):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO research_briefs
        (company_id, brief_text, business_model, competitive_position, management_quality,
         industry_dynamics, catalyst_detail, bear_case, key_metrics, comparable_companies, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        company_id,
        brief_data.get('brief_text', ''),
        brief_data.get('business_model', ''),
        brief_data.get('competitive_position', ''),
        brief_data.get('management_quality', ''),
        brief_data.get('industry_dynamics', ''),
        brief_data.get('catalyst_detail', ''),
        brief_data.get('bear_case', ''),
        json.dumps(brief_data.get('key_metrics', {})),
        json.dumps(brief_data.get('comparable_companies', [])),
        now
    ))
    conn.commit()
    conn.close()


def save_valuation(company_id, val_data: dict):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO valuations
        (company_id, dcf_bull, dcf_base, dcf_bear, dcf_weighted, dcf_wacc, dcf_terminal_growth,
         comps_ev_ebitda, comps_fwd_pe, comps_ev_fcf, comps_implied_value,
         ms_fair_value, ms_moat, ms_stars, ms_stewardship,
         current_price, weighted_intrinsic_value, margin_of_safety, valuation_confidence,
         sensitivity_table, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        company_id,
        val_data.get('dcf_bull'), val_data.get('dcf_base'), val_data.get('dcf_bear'),
        val_data.get('dcf_weighted'), val_data.get('dcf_wacc'), val_data.get('dcf_terminal_growth'),
        val_data.get('comps_ev_ebitda'), val_data.get('comps_fwd_pe'), val_data.get('comps_ev_fcf'),
        val_data.get('comps_implied_value'),
        val_data.get('ms_fair_value'), val_data.get('ms_moat'),
        val_data.get('ms_stars'), val_data.get('ms_stewardship'),
        val_data.get('current_price'), val_data.get('weighted_intrinsic_value'),
        val_data.get('margin_of_safety'), val_data.get('valuation_confidence'),
        json.dumps(val_data.get('sensitivity_table', {})),
        now
    ))
    conn.commit()
    conn.close()


def save_risk_assessment(company_id, risk_data: dict):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO risk_assessments
        (company_id, var_95, var_99, cvar_99, altman_z, altman_zone, fcf_conversion,
         earnings_quality_flags, fisher_score, fisher_breakdown, fisher_strengths,
         fisher_concerns, conviction_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        company_id,
        risk_data.get('var_95'), risk_data.get('var_99'), risk_data.get('cvar_99'),
        risk_data.get('altman_z'), risk_data.get('altman_zone'),
        risk_data.get('fcf_conversion'),
        json.dumps(risk_data.get('earnings_quality_flags', [])),
        risk_data.get('fisher_score'),
        json.dumps(risk_data.get('fisher_breakdown', {})),
        json.dumps(risk_data.get('fisher_strengths', [])),
        json.dumps(risk_data.get('fisher_concerns', [])),
        risk_data.get('conviction_score'),
        now
    ))
    conn.commit()
    conn.close()


def save_simulation(company_id, sim_data: dict):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO simulations
        (company_id, mirofish_project_id, mirofish_simulation_id,
         market_share_1yr, market_share_3yr, market_share_5yr,
         tam_current, tam_1yr, tam_3yr, tam_5yr,
         key_competitive_risk, bull_scenario, base_scenario, bear_scenario,
         simulation_confidence, full_report, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        company_id,
        sim_data.get('mirofish_project_id'), sim_data.get('mirofish_simulation_id'),
        sim_data.get('market_share_1yr'), sim_data.get('market_share_3yr'),
        sim_data.get('market_share_5yr'),
        sim_data.get('tam_current'), sim_data.get('tam_1yr'),
        sim_data.get('tam_3yr'), sim_data.get('tam_5yr'),
        sim_data.get('key_competitive_risk'),
        sim_data.get('bull_scenario'), sim_data.get('base_scenario'),
        sim_data.get('bear_scenario'), sim_data.get('simulation_confidence'),
        sim_data.get('full_report'), now
    ))
    conn.commit()
    conn.close()


def get_pipeline_summary():
    """Return count of companies at each stage."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT stage, COUNT(*) as count FROM companies GROUP BY stage
    """)
    rows = c.fetchall()
    conn.close()
    return {row['stage']: row['count'] for row in rows}


def get_companies_at_stage(stage):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM companies WHERE stage=? ORDER BY updated_date DESC", (stage,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_company_full_profile(company_id):
    """Get everything on a company — used for memo generation."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM companies WHERE id=?", (company_id,))
    company = dict(c.fetchone() or {})

    c.execute("SELECT * FROM research_briefs WHERE company_id=? ORDER BY created_at DESC LIMIT 1", (company_id,))
    row = c.fetchone()
    company['research'] = dict(row) if row else {}

    c.execute("SELECT * FROM valuations WHERE company_id=? ORDER BY created_at DESC LIMIT 1", (company_id,))
    row = c.fetchone()
    company['valuation'] = dict(row) if row else {}

    c.execute("SELECT * FROM risk_assessments WHERE company_id=? ORDER BY created_at DESC LIMIT 1", (company_id,))
    row = c.fetchone()
    company['risk'] = dict(row) if row else {}

    c.execute("SELECT * FROM simulations WHERE company_id=? ORDER BY created_at DESC LIMIT 1", (company_id,))
    row = c.fetchone()
    company['simulation'] = dict(row) if row else {}

    conn.close()
    return company


def log_decision(company_id, decision, decision_by, rationale,
                 entry_price=None, target_price=None, stop_loss=None,
                 position_size_pct=None, monitoring_criteria=None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO decisions
        (company_id, decision, decision_by, rationale, entry_price, target_price,
         stop_loss, position_size_pct, monitoring_criteria, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        company_id, decision, decision_by, rationale,
        entry_price, target_price, stop_loss, position_size_pct,
        json.dumps(monitoring_criteria or []), now
    ))
    c.execute("""
        UPDATE companies SET decision=?, decision_by=?, decision_date=?,
        decision_rationale=?, stage=?, updated_date=? WHERE id=?
    """, (decision, decision_by, now, rationale,
          'APPROVED' if decision == 'BUY' else ('WATCHING' if decision == 'WATCH' else 'REJECTED'),
          now, company_id))
    conn.commit()
    conn.close()


# Initialise on import
try:
    initialise_db()
except Exception as e:
    logger.warning(f"Walker pipeline DB init warning: {e}")
