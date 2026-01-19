//! Markdown rendering for chat messages.

use pulldown_cmark::{Event, Options, Parser, Tag, TagEnd};
use ratatui::{
    style::{Modifier, Style},
    text::{Line, Span},
};

use crate::theme::{colors, Styles};

/// Render markdown text to styled Lines with word wrapping.
pub fn render_markdown_wrapped(text: &str, base_style: Style, width: usize) -> Vec<Line<'static>> {
    let raw_lines = render_markdown(text, base_style);
    let mut wrapped_lines: Vec<Line<'static>> = Vec::new();

    for line in raw_lines {
        let wrapped = wrap_line(line, width);
        wrapped_lines.extend(wrapped);
    }

    wrapped_lines
}

/// Wrap a single Line to fit within width, preserving styles.
fn wrap_line(line: Line<'static>, width: usize) -> Vec<Line<'static>> {
    if width == 0 {
        return vec![line];
    }

    let mut result: Vec<Line<'static>> = Vec::new();
    let mut current_spans: Vec<Span<'static>> = Vec::new();
    let mut current_width: usize = 0;

    for span in line.spans {
        let style = span.style;
        let text = span.content.to_string();

        // Split text into words
        let mut chars = text.chars().peekable();
        let mut word = String::new();

        while let Some(c) = chars.next() {
            if c == ' ' || c == '\t' {
                // Process accumulated word
                if !word.is_empty() {
                    let word_len = word.chars().count();
                    if current_width + word_len > width && current_width > 0 {
                        // Wrap to new line
                        result.push(Line::from(std::mem::take(&mut current_spans)));
                        current_width = 0;
                    }
                    current_spans.push(Span::styled(std::mem::take(&mut word), style));
                    current_width += word_len;
                }
                // Add space if there's room
                if current_width < width {
                    current_spans.push(Span::styled(" ", style));
                    current_width += 1;
                }
            } else {
                word.push(c);
            }
        }

        // Process remaining word
        if !word.is_empty() {
            let word_len = word.chars().count();
            if current_width + word_len > width && current_width > 0 {
                result.push(Line::from(std::mem::take(&mut current_spans)));
                current_width = 0;
            }
            current_spans.push(Span::styled(word, style));
            current_width += word_len;
        }
    }

    // Flush remaining spans
    if !current_spans.is_empty() {
        result.push(Line::from(current_spans));
    }

    if result.is_empty() {
        result.push(Line::from(""));
    }

    result
}

/// Render markdown text to styled Lines (without wrapping).
pub fn render_markdown(text: &str, base_style: Style) -> Vec<Line<'static>> {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);

    let parser = Parser::new_ext(text, options);

    let mut lines: Vec<Line<'static>> = Vec::new();
    let mut current_spans: Vec<Span<'static>> = Vec::new();
    let mut style_stack: Vec<Style> = vec![base_style];

    // Track state
    let mut in_code_block = false;
    let mut code_block_content = String::new();

    for event in parser {
        match event {
            Event::Start(tag) => {
                let new_style = match tag {
                    Tag::Strong => current_style(&style_stack).add_modifier(Modifier::BOLD),
                    Tag::Emphasis => current_style(&style_stack).add_modifier(Modifier::ITALIC),
                    Tag::Strikethrough => {
                        current_style(&style_stack).add_modifier(Modifier::CROSSED_OUT)
                    }
                    Tag::CodeBlock(_) => {
                        in_code_block = true;
                        code_block_content.clear();
                        Style::default().fg(colors::AMBER)
                    }
                    Tag::Heading { .. } => {
                        current_style(&style_stack).add_modifier(Modifier::BOLD)
                    }
                    Tag::Link { .. } => Style::default()
                        .fg(colors::WAVE_BLUE)
                        .add_modifier(Modifier::UNDERLINED),
                    Tag::List(_) => current_style(&style_stack),
                    Tag::Item => {
                        // Add bullet point
                        current_spans.push(Span::styled("  • ", Styles::bot_label()));
                        current_style(&style_stack)
                    }
                    Tag::Paragraph => current_style(&style_stack),
                    Tag::BlockQuote(_) => Style::default()
                        .fg(colors::MIST)
                        .add_modifier(Modifier::ITALIC),
                    _ => current_style(&style_stack),
                };
                style_stack.push(new_style);
            }
            Event::End(tag_end) => {
                style_stack.pop();

                match tag_end {
                    TagEnd::CodeBlock => {
                        in_code_block = false;
                        // Render code block with background styling
                        for code_line in code_block_content.lines() {
                            lines.push(Line::from(vec![
                                Span::styled("  ", Style::default()),
                                Span::styled(
                                    format!(" {} ", code_line),
                                    Style::default().fg(colors::AMBER),
                                ),
                            ]));
                        }
                        code_block_content.clear();
                    }
                    TagEnd::Paragraph | TagEnd::Heading(_) => {
                        if !current_spans.is_empty() {
                            lines.push(Line::from(std::mem::take(&mut current_spans)));
                        }
                        lines.push(Line::from(""));
                    }
                    TagEnd::Item => {
                        if !current_spans.is_empty() {
                            lines.push(Line::from(std::mem::take(&mut current_spans)));
                        }
                    }
                    TagEnd::List(_) => {
                        lines.push(Line::from(""));
                    }
                    _ => {}
                }
            }
            Event::Text(text) => {
                if in_code_block {
                    code_block_content.push_str(&text);
                } else {
                    current_spans.push(Span::styled(text.to_string(), current_style(&style_stack)));
                }
            }
            Event::Code(code) => {
                // Inline code
                current_spans.push(Span::styled(
                    format!("`{}`", code),
                    Style::default().fg(colors::AMBER),
                ));
            }
            Event::SoftBreak => {
                if !current_spans.is_empty() {
                    lines.push(Line::from(std::mem::take(&mut current_spans)));
                }
            }
            Event::HardBreak => {
                if !current_spans.is_empty() {
                    lines.push(Line::from(std::mem::take(&mut current_spans)));
                }
            }
            Event::Rule => {
                if !current_spans.is_empty() {
                    lines.push(Line::from(std::mem::take(&mut current_spans)));
                }
                lines.push(Line::styled("────────────────", Styles::divider()));
            }
            _ => {}
        }
    }

    // Flush remaining spans
    if !current_spans.is_empty() {
        lines.push(Line::from(current_spans));
    }

    // Remove trailing empty lines
    while lines.last().map(|l| l.spans.is_empty()).unwrap_or(false) {
        lines.pop();
    }

    if lines.is_empty() {
        lines.push(Line::styled(text.to_string(), base_style));
    }

    lines
}

fn current_style(stack: &[Style]) -> Style {
    stack.last().copied().unwrap_or_default()
}
