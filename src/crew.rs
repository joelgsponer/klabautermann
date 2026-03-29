use askama::Template;
use askama_web::WebTemplate;
use axum::response::IntoResponse;

use crate::auth::middleware::AuthUser;

// ── Data ──────────────────────────────────────────────────

struct CrewMember {
    name: &'static str,
    role: &'static str,
    description: &'static str,
    active: bool,
}

const CREW: &[CrewMember] = &[
    CrewMember {
        name: "Sphinx",
        role: "First Mate",
        description: "Commands from the bridge. Memory like a black box recorder. Calm under fire. The organism\u{2019}s nervous system.",
        active: true,
    },
    CrewMember {
        name: "Echo",
        role: "Intelligence Officer",
        description: "Lurks in the signals room, headphones clamped over chrome-plated auditory implants. Sees patterns where others see static.",
        active: true,
    },
    CrewMember {
        name: "Forge",
        role: "Chief Engineer",
        description: "Grease-stained hands, augmented with micro-welders at the fingertips. Ships clean code like a shipwright ships watertight hulls.",
        active: true,
    },
    CrewMember {
        name: "Sentinel",
        role: "Security Officer",
        description: "One cybernetic eye that never blinks, scanning every bulkhead, every hatch, every line of code. Paranoid by design.",
        active: true,
    },
    CrewMember {
        name: "Compass",
        role: "Ship\u{2019}s Architect",
        description: "Charts courses through impossible waters. Thinks in systems. Speaks in blueprints.",
        active: true,
    },
    CrewMember {
        name: "Bosun",
        role: "Maintenance Chief",
        description: "Walks the decks at all hours, tightening what is loose, flagging what is stale. The ship runs because Bosun never stops.",
        active: true,
    },
    CrewMember {
        name: "Signal",
        role: "Communications Officer",
        description: "Every word that leaves this ship passes through Signal\u{2019}s hands. Turns raw data into prose that humans can parse.",
        active: true,
    },
    CrewMember {
        name: "Lookout",
        role: "Testing Officer",
        description: "Perched in the crow\u{2019}s nest with a telescope that can zoom to the pixel level. Does not trust. Verifies.",
        active: true,
    },
    CrewMember {
        name: "Quartermaster",
        role: "Memory & Graph Keeper",
        description: "Owns every record, every ledger, every node in the knowledge graph. Careful, methodical, precise.",
        active: true,
    },
    CrewMember {
        name: "Herald",
        role: "External Communications",
        description: "The face at the gangway. Handles all contact with the outside world \u{2014} Telegram, Discord, email. Knows every protocol.",
        active: true,
    },
    CrewMember {
        name: "Helmsman",
        role: "Scheduling & Automation",
        description: "Hands on the wheel, eyes on the clock. Manages cron jobs, reminders, and the thousand small automations that keep the ship on course.",
        active: true,
    },
    CrewMember {
        name: "Rigger",
        role: "Deployment & CI/CD",
        description: "Up in the rigging, lashing down the sails. Handles builds, releases, and the perilous business of getting code to the open sea.",
        active: true,
    },
];

// ── Template ──────────────────────────────────────────────

#[derive(Template, WebTemplate)]
#[template(path = "crew.html")]
struct CrewTemplate {
    username: String,
    crew: &'static [CrewMember],
}

// ── Handler ──────────────────────────────────────────────

/// GET /crew — render crew dashboard
pub async fn crew_page(user: AuthUser) -> impl IntoResponse {
    CrewTemplate {
        username: user.username,
        crew: CREW,
    }
}
