//! Header widget for title and status.

use ratatui::{
    layout::Rect,
    text::{Line, Span},
    widgets::Paragraph,
    Frame,
};

use crate::app::{App, ConnectionState};
use crate::theme::Styles;

/// Render the header with title and status.
pub fn render_header(frame: &mut Frame, area: Rect, app: &App) {
    let title = " ⚓ KLABAUTERMANN ";

    let (status_text, status_style) = match &app.connection_state {
        ConnectionState::Connecting => ("connecting...", Styles::loading()),
        ConnectionState::Connected => ("connected", Styles::status_connected()),
        ConnectionState::Disconnected => ("disconnected", Styles::status_error()),
        ConnectionState::Error(e) => (e.as_str(), Styles::status_error()),
    };

    let entity_count = if !app.entities.is_empty() {
        format!(" | {} entities", app.entities.len())
    } else {
        String::new()
    };

    let header = Paragraph::new(Line::from(vec![
        Span::styled(title, Styles::bot_label()),
        Span::styled("| ", Styles::help()),
        Span::styled(status_text, status_style),
        Span::styled(&entity_count, Styles::help()),
    ]));

    frame.render_widget(header, area);
}
