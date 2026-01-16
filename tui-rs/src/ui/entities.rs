//! Entity panel widget.

use ratatui::{
    layout::Rect,
    text::{Line, Span},
    widgets::Paragraph,
    Frame,
};

use crate::app::App;
use crate::theme::{entity_icon, Styles};

/// Render the entity panel showing recent entities.
pub fn render_entity_panel(frame: &mut Frame, area: Rect, app: &App) {
    let mut lines: Vec<Line> = Vec::new();

    // Header
    lines.push(Line::from(vec![
        Span::styled("─── ", Styles::divider()),
        Span::styled("Recent Entities ", Styles::bot_label()),
        Span::styled("(Ctrl+E to toggle) ", Styles::help()),
        Span::styled(
            "─".repeat((area.width as usize).saturating_sub(35)),
            Styles::divider(),
        ),
    ]));

    // Show last 5 entities
    for entity in app.entities.iter().take(5) {
        let icon = entity_icon(&entity.entity_type);
        lines.push(Line::from(vec![
            Span::styled(format!("  {} ", icon), Styles::entity_icon()),
            Span::styled(&entity.name, Styles::message()),
            Span::styled(format!(" ({})", entity.entity_type), Styles::help()),
        ]));
    }

    let panel = Paragraph::new(lines);
    frame.render_widget(panel, area);
}
