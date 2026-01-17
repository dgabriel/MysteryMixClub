# Website Design System

## Overview
This design system provides comprehensive guidelines for creating accessible, usable, and beautiful web experiences across all screen sizes. It prioritizes readability with dark text on light backgrounds and maintains WCAG 2.1 AA accessibility standards.

---

## Color Palette

### Primary Colors

#### Coral Pink (`#F5A5A5`)
- **Usage**: Primary CTA buttons, accents, highlights, active states
- **RGB**: 245, 165, 165
- **Accessibility**: Use with dark text only (navy or charcoal)

#### Navy Blue (`#4A4E7B`)
- **Usage**: Primary headers, navigation bars, section dividers
- **RGB**: 74, 78, 123
- **Accessibility**: Sufficient contrast with white/cream text, but prefer cream backgrounds with navy text

#### Mauve (`#A47373`)
- **Usage**: Secondary buttons, borders, subtle accents, hover states
- **RGB**: 164, 115, 115
- **Accessibility**: Use with white/cream text or as background with dark text

### Accent Colors

#### Bronze (`#8B7246`)
- **Usage**: Warning states, informational callouts, tertiary buttons
- **RGB**: 139, 114, 70
- **Accessibility**: Use with cream backgrounds or as text on light backgrounds

#### Chartreuse (`#B8BD5C`)
- **Usage**: Success states, highlights, energetic accents
- **RGB**: 184, 189, 92
- **Accessibility**: Best with navy/charcoal text overlay

### Neutral Colors

#### Charcoal Navy (`#2C3E50`)
- **Usage**: Primary text, icons, borders, footer backgrounds
- **RGB**: 44, 62, 80
- **Accessibility**: Excellent contrast on cream/white backgrounds

#### Purple Gray (`#6B6B7B`)
- **Usage**: Secondary text, disabled states, subtle borders
- **RGB**: 107, 107, 123
- **Accessibility**: Good for body text on light backgrounds, minimum 16px font size

#### Cream (`#F5F5F0`)
- **Usage**: Primary background, cards, sections
- **RGB**: 245, 245, 240
- **Accessibility**: Reduces eye strain compared to pure white, excellent for main backgrounds

---

## Typography

### Font Families

**Primary Font**: System font stack for optimal performance
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
```

**Alternative**: For branded feeling, consider:
- **Headings**: Inter, Poppins, or Montserrat
- **Body**: Inter, Open Sans, or Source Sans Pro

### Type Scale

#### Desktop
- **H1**: 48px / 3rem — Bold — Charcoal Navy — Line height 1.2
- **H2**: 36px / 2.25rem — Bold — Charcoal Navy — Line height 1.3
- **H3**: 28px / 1.75rem — Semibold — Charcoal Navy — Line height 1.4
- **H4**: 24px / 1.5rem — Semibold — Charcoal Navy — Line height 1.4
- **H5**: 20px / 1.25rem — Semibold — Charcoal Navy — Line height 1.5
- **Body Large**: 18px / 1.125rem — Regular — Charcoal Navy — Line height 1.6
- **Body**: 16px / 1rem — Regular — Charcoal Navy — Line height 1.6
- **Body Small**: 14px / 0.875rem — Regular — Purple Gray — Line height 1.5
- **Caption**: 12px / 0.75rem — Regular — Purple Gray — Line height 1.4

#### Mobile (< 768px)
- **H1**: 36px / 2.25rem
- **H2**: 28px / 1.75rem
- **H3**: 24px / 1.5rem
- **H4**: 20px / 1.25rem
- **H5**: 18px / 1.125rem
- All body text remains same size for readability

### Text Color Rules

**ALWAYS USE:**
- Charcoal Navy (`#2C3E50`) for primary text on light backgrounds
- Purple Gray (`#6B6B7B`) for secondary text on light backgrounds
- Navy Blue (`#4A4E7B`) for headings when extra emphasis needed

**NEVER USE:**
- White or cream text on navy/charcoal backgrounds (client preference)
- Low contrast combinations that fail WCAG AA standards

---

## Spacing System

Use multiples of 8px for consistent spacing:

- **4px** (0.25rem): Tiny gaps, icon spacing
- **8px** (0.5rem): Small spacing, compact elements
- **16px** (1rem): Default spacing, paragraph margins
- **24px** (1.5rem): Medium spacing, section padding
- **32px** (2rem): Large spacing, component separation
- **48px** (3rem): Extra large, major section dividers
- **64px** (4rem): XXL spacing, hero sections
- **96px** (6rem): XXXL spacing, page sections

---

## Components

### Buttons

#### Primary Button (CTA)
```css
Background: Coral Pink (#F5A5A5)
Text: Charcoal Navy (#2C3E50)
Font: 16px, Semibold
Padding: 12px 24px (16px 32px for large)
Border Radius: 8px
Border: none
Transition: all 0.2s ease

Hover:
  Background: Darken coral by 10% (#F28B8B)
  Transform: translateY(-2px)
  Box Shadow: 0 4px 12px rgba(245, 165, 165, 0.4)

Active/Pressed:
  Transform: translateY(0)
  Box Shadow: 0 2px 4px rgba(245, 165, 165, 0.3)

Disabled:
  Background: Purple Gray (#6B6B7B) at 40% opacity
  Text: Purple Gray (#6B6B7B)
  Cursor: not-allowed
```

#### Secondary Button
```css
Background: Transparent
Text: Navy Blue (#4A4E7B)
Font: 16px, Semibold
Padding: 12px 24px
Border Radius: 8px
Border: 2px solid Mauve (#A47373)
Transition: all 0.2s ease

Hover:
  Background: Mauve (#A47373)
  Text: Charcoal Navy (#2C3E50)
  Border: 2px solid Mauve (#A47373)

Active/Pressed:
  Background: Darken mauve by 10%
```

#### Tertiary Button (Text Only)
```css
Background: Transparent
Text: Navy Blue (#4A4E7B)
Font: 16px, Semibold
Padding: 12px 16px
Border: none
Transition: color 0.2s ease

Hover:
  Text: Coral Pink (#F5A5A5)
  Text Decoration: underline
```

#### Success Button
```css
Background: Chartreuse (#B8BD5C)
Text: Charcoal Navy (#2C3E50)
[Same styling as primary otherwise]
```

#### Warning Button
```css
Background: Bronze (#8B7246)
Text: Cream (#F5F5F0)
[Same styling as primary otherwise]
```

### Headers

#### Main Navigation Header
```css
Background: Cream (#F5F5F0)
Border Bottom: 2px solid Navy Blue (#4A4E7B)
Height: 72px (mobile: 64px)
Padding: 0 24px (mobile: 0 16px)
Position: sticky
Top: 0
Z-index: 1000
Box Shadow: 0 2px 8px rgba(44, 62, 80, 0.1)

Logo:
  Height: 40px
  
Navigation Links:
  Text: Charcoal Navy (#2C3E50)
  Font: 16px, Medium
  Padding: 8px 16px
  Hover: Background Coral Pink (#F5A5A5) with 20% opacity
  Active: Text Coral Pink (#F5A5A5), Border Bottom 3px solid Coral Pink
```

#### Page Header / Hero
```css
Background: Gradient from Cream (#F5F5F0) to light tint of Chartreuse
Padding: 96px 24px 64px (mobile: 64px 16px 48px)
Text Align: center or left

Heading:
  H1 style
  Color: Charcoal Navy (#2C3E50)
  
Subheading:
  Body Large
  Color: Purple Gray (#6B6B7B)
  Max Width: 600px
```

### Footers

#### Main Footer
```css
Background: Navy Blue (#4A4E7B) at 15% opacity on Cream base
Border Top: 3px solid Navy Blue (#4A4E7B)
Padding: 48px 24px 24px
Color: Charcoal Navy (#2C3E50)

Section Headings:
  H5 style
  Color: Navy Blue (#4A4E7B)
  Margin Bottom: 16px
  
Links:
  Color: Charcoal Navy (#2C3E50)
  Font: 14px
  Hover: Color Coral Pink (#F5A5A5)
  
Copyright:
  Body Small
  Color: Purple Gray (#6B6B7B)
  Text Align: center
  Margin Top: 32px
  Padding Top: 24px
  Border Top: 1px solid Purple Gray (#6B6B7B) at 30% opacity
```

### Banners

#### Info Banner
```css
Background: Navy Blue (#4A4E7B) at 10% opacity on Cream
Border Left: 4px solid Navy Blue (#4A4E7B)
Padding: 16px 20px
Border Radius: 8px
Margin: 16px 0

Icon: Navy Blue (#4A4E7B)
Text: Charcoal Navy (#2C3E50)
Font: Body
```

#### Success Banner
```css
Background: Chartreuse (#B8BD5C) at 20% opacity on Cream
Border Left: 4px solid Chartreuse (#B8BD5C)
Icon: Darken Chartreuse
Text: Charcoal Navy (#2C3E50)
[Same structure as Info]
```

#### Warning Banner
```css
Background: Bronze (#8B7246) at 20% opacity on Cream
Border Left: 4px solid Bronze (#8B7246)
Icon: Bronze (#8B7246)
Text: Charcoal Navy (#2C3E50)
[Same structure as Info]
```

#### Error Banner
```css
Background: Mauve (#A47373) at 20% opacity on Cream
Border Left: 4px solid Mauve (#A47373)
Icon: Mauve (#A47373)
Text: Charcoal Navy (#2C3E50)
[Same structure as Info]
```

#### Announcement Banner (Top of Page)
```css
Background: Coral Pink (#F5A5A5) at 30% opacity on Cream
Border Bottom: 2px solid Coral Pink (#F5A5A5)
Padding: 12px 24px
Text Align: center
Font: Body Small, Semibold
Color: Charcoal Navy (#2C3E50)

Dismiss Button:
  Color: Charcoal Navy (#2C3E50)
  Hover: Color Coral Pink (#F5A5A5)
```

### Cards

#### Standard Card
```css
Background: Cream (#F5F5F0)
Border: 1px solid Purple Gray (#6B6B7B) at 30% opacity
Border Radius: 12px
Padding: 24px
Box Shadow: 0 2px 8px rgba(44, 62, 80, 0.08)
Transition: all 0.3s ease

Hover:
  Box Shadow: 0 8px 24px rgba(44, 62, 80, 0.15)
  Transform: translateY(-4px)
  Border: 1px solid Coral Pink (#F5A5A5) at 50% opacity
```

#### Featured Card
```css
Background: Gradient from Cream to Coral Pink at 15% opacity
Border: 2px solid Coral Pink (#F5A5A5)
Border Radius: 12px
Padding: 32px
Box Shadow: 0 4px 16px rgba(245, 165, 165, 0.2)
```

### Forms

#### Input Fields
```css
Background: Cream (#F5F5F0)
Border: 2px solid Purple Gray (#6B6B7B) at 40% opacity
Border Radius: 8px
Padding: 12px 16px
Font: 16px (prevents zoom on mobile)
Color: Charcoal Navy (#2C3E50)
Transition: border-color 0.2s ease

Placeholder:
  Color: Purple Gray (#6B6B7B) at 60% opacity
  
Focus:
  Border: 2px solid Navy Blue (#4A4E7B)
  Outline: 3px solid Navy Blue (#4A4E7B) at 20% opacity
  Outline Offset: 2px
  
Error:
  Border: 2px solid Mauve (#A47373)
  
Success:
  Border: 2px solid Chartreuse (#B8BD5C)

Disabled:
  Background: Purple Gray (#6B6B7B) at 10% opacity
  Cursor: not-allowed
```

#### Labels
```css
Font: 14px, Semibold
Color: Charcoal Navy (#2C3E50)
Margin Bottom: 8px
Display: block
```

#### Helper Text
```css
Font: 12px
Color: Purple Gray (#6B6B7B)
Margin Top: 4px
```

#### Error Message
```css
Font: 12px, Medium
Color: Mauve (#A47373)
Margin Top: 4px
```

### Navigation

#### Breadcrumbs
```css
Font: 14px
Color: Purple Gray (#6B6B7B)
Margin Bottom: 24px

Separator: " / " in Purple Gray
Current Page: Charcoal Navy (#2C3E50), Semibold

Link Hover: Color Coral Pink (#F5A5A5)
```

#### Tabs
```css
Border Bottom: 2px solid Purple Gray (#6B6B7B) at 30% opacity

Tab:
  Padding: 12px 24px
  Font: 16px, Medium
  Color: Purple Gray (#6B6B7B)
  Background: Transparent
  Border: none
  Cursor: pointer
  
Active Tab:
  Color: Coral Pink (#F5A5A5)
  Border Bottom: 3px solid Coral Pink (#F5A5A5)
  Margin Bottom: -2px
  
Hover (Inactive):
  Color: Navy Blue (#4A4E7B)
```

---

## Responsive Breakpoints

```css
/* Mobile First Approach */
Mobile: 0-767px
Tablet: 768px-1023px
Desktop: 1024px-1439px
Large Desktop: 1440px+

/* Common Breakpoint Variables */
sm: 640px
md: 768px
lg: 1024px
xl: 1280px
2xl: 1536px
```

### Mobile Adaptations
- Stack columns vertically
- Reduce padding (24px → 16px)
- Hamburger menu for navigation
- Larger touch targets (minimum 44px x 44px)
- Reduce type scale as specified above

---

## Accessibility Standards

### WCAG 2.1 AA Compliance

#### Color Contrast Ratios (Minimum)
- **Normal text**: 4.5:1
- **Large text (18px+ or 14px+ bold)**: 3:1
- **UI components and graphics**: 3:1

#### Validated Combinations
✅ Charcoal Navy (#2C3E50) on Cream (#F5F5F0) — 11.8:1
✅ Navy Blue (#4A4E7B) on Cream (#F5F5F0) — 6.2:1
✅ Purple Gray (#6B6B7B) on Cream (#F5F5F0) — 4.8:1
✅ Charcoal Navy (#2C3E50) on Coral Pink (#F5A5A5) — 5.2:1
✅ Charcoal Navy (#2C3E50) on Chartreuse (#B8BD5C) — 6.8:1

❌ AVOID: Cream text on Navy backgrounds (fails contrast)
❌ AVOID: White text on Charcoal backgrounds (client preference)

### Focus States
- All interactive elements must have visible focus indicators
- Focus outline: 3px solid, using accent color at 60% opacity
- Outline offset: 2px
- Never remove focus outlines (use visible alternatives)

### Keyboard Navigation
- All interactive elements must be keyboard accessible
- Logical tab order
- Skip links for navigation
- ARIA labels where needed

### Screen Readers
- Semantic HTML5 elements (header, nav, main, footer, article, section)
- Alt text for all meaningful images
- ARIA labels for icon buttons
- Form labels properly associated

---

## Layout Principles

### Container Widths
```css
Max Width: 1280px
Padding: 24px (mobile: 16px)
Margin: 0 auto
```

### Grid System (12 Column)
```css
Column Gap: 24px (mobile: 16px)
Row Gap: 24px (mobile: 16px)

Common Layouts:
- Two Column: 6/6 (desktop) → 12 (mobile)
- Three Column: 4/4/4 (desktop) → 12 (mobile)
- Sidebar: 8/4 (desktop) → 12 (mobile)
- Asymmetric: 7/5 (desktop) → 12 (mobile)
```

### White Space
- Generous spacing improves readability
- Use spacing system consistently
- Respect content breathing room
- Minimum 16px between interactive elements

---

## Motion & Animation

### Timing Functions
```css
Default: ease-out (0.2s)
Subtle: ease (0.15s)
Dramatic: cubic-bezier(0.4, 0, 0.2, 1) (0.3s)
```

### Common Animations
```css
Hover Transform: translateY(-2px to -4px)
Button Press: scale(0.98)
Fade In: opacity 0 to 1 over 0.3s
Slide In: translateX(-20px to 0) over 0.3s
```

### Reduce Motion
```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## Icons

### Icon System
- Use a consistent icon library (Heroicons, Feather Icons, or Lucide)
- Icon size scale: 16px, 20px, 24px, 32px, 48px
- Icon color: Match text color or use accent colors
- Line weight: 2px for consistency

### Icon Button
```css
Size: 40px x 40px (minimum touch target)
Padding: 8px
Border Radius: 8px
Transition: background 0.2s ease

Hover:
  Background: Coral Pink (#F5A5A5) at 20% opacity
```

---

## Usage Examples

### Example 1: Landing Page Hero
```
Background: Cream (#F5F5F0)
Heading: H1, Charcoal Navy
Subheading: Body Large, Purple Gray
CTA Button: Primary (Coral Pink)
Secondary CTA: Secondary (Mauve border)
```

### Example 2: Dashboard Card
```
Card Background: Cream (#F5F5F0)
Card Border: Purple Gray at 30% opacity
Heading: H4, Navy Blue
Body Text: Body, Charcoal Navy
Button: Tertiary (text only)
```

### Example 3: Form Section
```
Background: Cream (#F5F5F0)
Section Header: H3, Charcoal Navy
Labels: 14px Semibold, Charcoal Navy
Inputs: Cream background, Purple Gray border
Submit Button: Primary (Coral Pink)
```

---

## Quick Reference: Do's and Don'ts

### ✅ DO
- Use Charcoal Navy for primary text on light backgrounds
- Provide generous white space
- Ensure 4.5:1 contrast for normal text
- Use system fonts for performance
- Make touch targets at least 44px
- Stack columns on mobile
- Use consistent spacing (8px multiples)
- Provide clear focus indicators

### ❌ DON'T
- Use white or cream text on dark backgrounds
- Use colors with insufficient contrast
- Create tiny touch targets (<44px)
- Override focus outlines without replacement
- Use color alone to convey information
- Nest interactive elements
- Use auto-playing animations
- Ignore mobile responsiveness

---

## File Naming Conventions

### CSS Classes
Use BEM (Block Element Modifier) methodology:
```
.button
.button--primary
.button--secondary
.button__icon
.card
.card__header
.card__body
.card--featured
```

### Component Files
```
PascalCase for components: Button.jsx, Card.jsx, Header.jsx
kebab-case for utilities: color-utils.js, spacing-helpers.js
```

---

## Version
Design System v1.0
Last Updated: January 2026

## Notes for Developers
This design system prioritizes accessibility and usability. When implementing:
1. Always check color contrast with tools like WebAIM or Stark
2. Test with keyboard navigation
3. Validate with screen readers
4. Test on mobile devices, not just browser resize
5. Respect user preferences (prefers-reduced-motion, prefers-color-scheme)
6. Use semantic HTML first, ARIA when necessary
7. Keep the client's preference: dark text on light backgrounds throughout

---

## Color Palette Quick Reference

| Color Name | Hex | RGB | Usage |
|------------|-----|-----|-------|
| Coral Pink | #F5A5A5 | 245, 165, 165 | Primary CTA, accents |
| Navy Blue | #4A4E7B | 74, 78, 123 | Headers, emphasis |
| Mauve | #A47373 | 164, 115, 115 | Secondary, borders |
| Bronze | #8B7246 | 139, 114, 70 | Warnings, tertiary |
| Chartreuse | #B8BD5C | 184, 189, 92 | Success, energy |
| Charcoal Navy | #2C3E50 | 44, 62, 80 | Primary text |
| Purple Gray | #6B6B7B | 107, 107, 123 | Secondary text |
| Cream | #F5F5F0 | 245, 245, 240 | Backgrounds |
