//! Chat viewport widget for message history.

use ratatui::{
    layout::Rect,
    text::{Line, Span, Text},
    widgets::Paragraph,
    Frame,
};
use textwrap::wrap;

use super::markdown::render_markdown_wrapped;
use crate::app::App;
use crate::theme::Styles;

/// Render the chat viewport with message history.
pub fn render_chat(frame: &mut Frame, area: Rect, app: &mut App) {
    if app.messages.is_empty() {
        render_welcome(frame, area);
        return;
    }

    // Calculate wrap width (leave margin for borders)
    let wrap_width = (area.width as usize).saturating_sub(4).max(20);

    let mut lines: Vec<Line> = Vec::new();

    for msg in &app.messages {
        let (label, label_style) = if msg.is_user {
            ("You: ", Styles::user_label())
        } else {
            ("\u{2693} Klabautermann: ", Styles::bot_label())
        };

        if msg.is_user {
            // User messages: simple text wrapping
            let wrapped = wrap(&msg.content, wrap_width.saturating_sub(18));

            for (i, line_text) in wrapped.iter().enumerate() {
                if i == 0 {
                    lines.push(Line::from(vec![
                        Span::styled(label, label_style),
                        Span::styled(line_text.to_string(), Styles::message()),
                    ]));
                } else {
                    lines.push(Line::from(vec![
                        Span::raw("  "),
                        Span::styled(line_text.to_string(), Styles::message()),
                    ]));
                }
            }
        } else {
            // Bot messages: render with markdown and word wrapping
            lines.push(Line::from(Span::styled(label, label_style)));

            // Account for indentation in wrap width
            let md_wrap_width = wrap_width.saturating_sub(2);
            let md_lines = render_markdown_wrapped(&msg.content, Styles::message(), md_wrap_width);
            for md_line in md_lines {
                // Indent markdown content
                let mut indented_spans = vec![Span::raw("  ")];
                indented_spans.extend(md_line.spans);
                lines.push(Line::from(indented_spans));
            }
        }

        // Add spacing between messages
        lines.push(Line::from(""));
    }

    // Update scroll state in app
    let total_lines = lines.len();
    let viewport_height = area.height as usize;
    app.update_scroll(total_lines, viewport_height);

    // Show scroll indicator if not at bottom
    if !app.auto_scroll && total_lines > viewport_height {
        let indicator = format!(
            " [{}/{}] ↑↓ scroll, End=bottom ",
            app.scroll_offset + viewport_height,
            total_lines
        );
        lines.push(Line::styled(indicator, Styles::help()));
    }

    let chat = Paragraph::new(Text::from(lines)).scroll((app.scroll_offset as u16, 0));
    frame.render_widget(chat, area);
}

/// ASCII art banner for the welcome screen.
const BANNER: &[&str] = &[
    r"      ⚓",
    r"     ╱│╲",
    r"    ╱ │ ╲       ██╗  ██╗██╗      █████╗ ██████╗  █████╗ ██╗   ██╗████████╗",
    r"   ╱  │  ╲      ██║ ██╔╝██║     ██╔══██╗██╔══██╗██╔══██╗██║   ██║╚══██╔══╝",
    r"  ╱   │   ╲     █████╔╝ ██║     ███████║██████╔╝███████║██║   ██║   ██║   ",
    r" ╱    │    ╲    ██╔═██╗ ██║     ██╔══██║██╔══██╗██╔══██║██║   ██║   ██║   ",
    r"╱─────┴─────╲   ██║  ██╗███████╗██║  ██║██████╔╝██║  ██║╚██████╔╝   ██║   ",
    r"╲───────────╱   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝ ╚═════╝    ╚═╝   ",
    r" ╲─────────╱              ════════════════════════════════════════════",
    r"  ╲───────╱                     Your Personal Knowledge Navigator",
    r"   ╲─────╱",
    r"    ╲   ╱",
    r"     ╲ ╱",
    r"      V",
];

/// Compact banner for smaller terminals.
const BANNER_SMALL: &[&str] = &[
    r"  ⚓ KLABAUTERMANN ⚓",
    r"  ══════════════════",
    r"  Knowledge Navigator",
];

/// Render the welcome message when chat is empty.
fn render_welcome(frame: &mut Frame, area: Rect) {
    let mut lines: Vec<Line> = Vec::new();

    // Choose banner based on terminal width
    let banner = if area.width >= 75 { BANNER } else { BANNER_SMALL };

    // Add banner with wave blue color
    for line in banner {
        lines.push(Line::styled(*line, Styles::bot_label()));
    }

    // Add spacing
    lines.push(Line::from(""));
    lines.push(Line::from(""));

    // Welcome message
    lines.push(Line::from(vec![
        Span::styled("  Ahoy, Captain! ", Styles::user_label()),
        Span::styled(
            "I'm your personal knowledge navigator.",
            Styles::message(),
        ),
    ]));
    lines.push(Line::from(""));

    // Help text
    lines.push(Line::styled(
        "  Tell me about people you meet, projects you're working on,",
        Styles::help(),
    ));
    lines.push(Line::styled(
        "  or ask me anything about your knowledge graph!",
        Styles::help(),
    ));
    lines.push(Line::from(""));

    // Keyboard shortcuts - vim mode
    lines.push(Line::from(vec![
        Span::styled("  Vim Mode: ", Styles::bot_label()),
        Span::styled("i", Styles::user_label()),
        Span::styled(" insert  ", Styles::help()),
        Span::styled("Esc/kj", Styles::user_label()),
        Span::styled(" normal  ", Styles::help()),
        Span::styled("j/k", Styles::user_label()),
        Span::styled(" scroll  ", Styles::help()),
        Span::styled("g/G", Styles::user_label()),
        Span::styled(" top/bottom", Styles::help()),
    ]));
    lines.push(Line::from(vec![
        Span::styled("  Shortcuts: ", Styles::bot_label()),
        Span::styled("Ctrl+E", Styles::user_label()),
        Span::styled(" entities  ", Styles::help()),
        Span::styled("Ctrl+L", Styles::user_label()),
        Span::styled(" clear  ", Styles::help()),
        Span::styled("Ctrl+C", Styles::user_label()),
        Span::styled(" quit", Styles::help()),
    ]));

    let welcome = Paragraph::new(Text::from(lines));
    frame.render_widget(welcome, area);
}
