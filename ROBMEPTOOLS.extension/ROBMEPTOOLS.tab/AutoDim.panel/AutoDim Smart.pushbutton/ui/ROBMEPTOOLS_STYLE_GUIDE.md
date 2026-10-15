# ROBMEPTOOLS UI System — v2

Fab Hover is the proof-of-concept implementation for the shared ROBMEPTOOLS Revit UI language.
The goal is not for every tool to use the same layout. The goal is for every tool to use the
same design tokens, controls, states, spacing, typography, interaction patterns, and error/status language.

## Runtime resources
- `ROBMEPTOOLS.Theme.xaml` — color/spacing/sizing design tokens.
- `ROBMEPTOOLS.Controls.xaml` — reusable buttons, cards, toggles, radios, search inputs, badges and text styles.
- `ROBMEPTOOLS.Icons.xaml` — standard Windows UI glyphs for navigation/actions only.
- `ROBMEPTOOLS_MENU_TEMPLATE.xaml` — reference shell for future settings-style tools.

Production windows merge these dictionaries and consume them with `DynamicResource`. Avoid new hard-coded
colors unless the color has semantic meaning unique to a single tool.

## Design goals
- Professional engineering-tool appearance; dark navy base and restrained accents.
- Dense but readable. Use space to clarify hierarchy, not to decorate.
- No generated pseudo-MEP artwork in production menus.
- Navigation/actions use familiar platform glyphs. MEP/workflow identity uses literal text badges (HVAC, PL, EQ, etc.).
- Every visible control must map to working functionality.
- Windows are resizable and keyboard-focusable.
- Long lists should support search/filter instead of becoming walls of toggles.
- Preview work is debounced; expensive work is never performed on every slider pixel/keystroke.
- Advanced/diagnostic controls stay out of the daily-use path.

## Benchmark patterns
The system intentionally follows patterns seen in mature Revit/pyRevit tooling:
- resource dictionaries instead of giant one-off XAML blobs;
- modeless/persistent state kept independent of transient invocation context;
- debounced search/preview updates;
- descriptive labels, compact metadata/status badges, and useful empty states;
- resizable utility windows;
- on-demand data evaluation instead of eager inspection.

## Layout rules
- Sidebar: ~214 px.
- Header: 76 px.
- Footer: 60 px.
- Page gutter: 20–22 px.
- Card padding: 14–16 px.
- Card radius: 8 px.
- Primary text uses Segoe UI, with normal Windows UI glyphs from Segoe MDL2 Assets.
- Overview pages summarize real state and provide useful shortcuts; they are not help pages.

## Interaction rules
1. Use `NavButton` / `NavButtonActive` for sidebar navigation.
2. Use `ActionButton` for secondary actions and `PrimaryButton` for the one primary action in a region.
3. Use `FieldToggle` for boolean settings. Do not pair it with a second checkbox.
4. Use `ChoiceRadio` for mutually exclusive text options and `SwatchRadio` for color choices.
5. Use `SearchTextBox` for lists larger than one compact screen.
6. Show empty states when a search/filter produces nothing.
7. Mark unsaved settings visibly but quietly.
8. Keep Apply/Cancel placement consistent across settings-style tools.
9. Use semantic badges only when they clarify a discipline/workflow immediately.

## Reuse workflow
For the next ROBMEPTOOLS tool:
1. Copy the menu template.
2. Merge the same Theme / Icons / Controls dictionaries.
3. Keep the shell, status/footer behavior, and component styles unchanged.
4. Replace only the page map and tool-specific content.
5. Add search for large parameter/option lists.
6. Keep runtime logic separate from the UI layer.
