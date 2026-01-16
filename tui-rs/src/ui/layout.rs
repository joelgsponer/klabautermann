//! Layout calculations and main render function.

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    text::{Line, Span},
    widgets::Paragraph,
    Frame,
};

use crate::app::App;
use crate::theme::Styles;

use super::chat::render_chat;
use super::entities::render_entity_panel;
use super::header::render_header;
use super::input::render_input;
use super::loading::render_loading;

/// Main render function for the application.
pub fn render(frame: &mut Frame, app: &mut App) {
    let area = frame.area();

    // Handle quitting state
    if app.quitting {
        let farewell = Paragraph::new(Line::from(Span::styled(
            "Fair winds and following seas, Captain!",
            Styles::bot_label(),
        )));
        frame.render_widget(farewell, area);
        return;
    }

    // Handle initial loading state
    if !app.ready {
        let loading = Paragraph::new(Line::from(vec![
            Span::styled(
                format!("{} ", crate::theme::SPINNER_FRAMES[app.spinner_frame]),
                Styles::spinner(),
            ),
            Span::styled("Launching vessel...", Styles::loading()),
        ]));
        frame.render_widget(loading, area);
        return;
    }

    // Calculate layout
    let show_entities = app.show_entities && !app.entities.is_empty();
    let entity_height = if show_entities {
        (app.entities.len().min(5) + 3) as u16
    } else {
        0
    };
    let loading_height = if app.waiting { 1 } else { 0 };

    let constraints = vec![
        Constraint::Length(1),            // Header
        Constraint::Length(1),            // Top divider
        Constraint::Min(5),               // Chat viewport
        Constraint::Length(entity_height), // Entity panel (0 if hidden)
        Constraint::Length(loading_height), // Loading indicator (0 if not waiting)
        Constraint::Length(1),            // Bottom divider
        Constraint::Length(3),            // Input area
    ];

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints(constraints)
        .split(area);

    // Render header
    render_header(frame, chunks[0], app);

    // Render top divider
    render_divider(frame, chunks[1]);

    // Render chat viewport
    render_chat(frame, chunks[2], app);

    // Render entity panel (if visible)
    if show_entities {
        render_entity_panel(frame, chunks[3], app);
    }

    // Render loading indicator (if waiting)
    if app.waiting {
        render_loading(frame, chunks[4], app);
    }

    // Render bottom divider
    render_divider(frame, chunks[5]);

    // Render input area
    render_input(frame, chunks[6], app);
}

/// Render a horizontal divider.
fn render_divider(frame: &mut Frame, area: Rect) {
    let divider = Paragraph::new(Line::from(Span::styled(
        "\u{2500}".repeat(area.width as usize),
        Styles::divider(),
    )));
    frame.render_widget(divider, area);
}
