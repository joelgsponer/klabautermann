//! Loading indicator widget.

use ratatui::{
    layout::Rect,
    text::{Line, Span},
    widgets::Paragraph,
    Frame,
};

use crate::app::App;
use crate::theme::{Styles, SPINNER_FRAMES};

/// Render the loading indicator.
pub fn render_loading(frame: &mut Frame, area: Rect, app: &App) {
    let spinner = SPINNER_FRAMES[app.spinner_frame];

    let loading = Paragraph::new(Line::from(vec![
        Span::styled(format!(" {} ", spinner), Styles::spinner()),
        Span::styled(&app.loading_message, Styles::loading()),
    ]));

    frame.render_widget(loading, area);
}
