//! Input area widget.

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    text::{Line, Span},
    widgets::Paragraph,
    Frame,
};

use crate::app::{App, InputMode};
use crate::theme::Styles;

/// Render the input area with prompt and text input.
pub fn render_input(frame: &mut Frame, area: Rect, app: &App) {
    // Mode indicator width (e.g., "[NORMAL] " or "[INSERT] ")
    let mode_width = 10;

    // Split into mode, prompt, and input areas
    let chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Length(mode_width),
            Constraint::Length(2),
            Constraint::Min(1),
        ])
        .split(area);

    // Render mode indicator
    let (mode_text, mode_style) = match app.input_mode {
        InputMode::Normal => ("[NORMAL] ", Styles::bot_label()),
        InputMode::Insert => ("[INSERT] ", Styles::user_label()),
    };
    let mode_indicator = Paragraph::new(Line::from(Span::styled(mode_text, mode_style)));
    frame.render_widget(mode_indicator, chunks[0]);

    // Render prompt
    let prompt = Paragraph::new(Line::from(Span::styled("> ", Styles::input_prompt())));
    frame.render_widget(prompt, chunks[1]);

    // Render text area
    frame.render_widget(&app.input, chunks[2]);
}
