import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { OnboardingGuideModal } from "./OnboardingGuideModal";
import { ReleaseNotesModal } from "./ReleaseNotesModal";
import { ReportContentModal } from "./ReportContentModal";

/**
 * ADR 0038 (MysteryMixClub-3fjt): every modal is a white panel with a dark
 * border, and nothing inside it uses the dark ramp, which is invisible (or
 * fails contrast) on white. One guard for all of them so a new or edited
 * modal can't drift back to the dark `sheet`.
 */
const DARK_RAMP =
  /\b(bg-sheet|text-foreground|text-muted-foreground|text-subtle-foreground|text-destructive-text|hover:text-accent)\b/;

function expectPaperModal() {
  const dialog = screen.getByRole("dialog");
  expect(dialog.className).toMatch(/\bbg-paper\b/);
  expect(dialog.className).toMatch(/\bborder-ink\b/);
  for (const el of [dialog, ...dialog.querySelectorAll("*")]) {
    expect(el.getAttribute("class") ?? "").not.toMatch(DARK_RAMP);
  }
}

describe("modal surface (ADR 0038)", () => {
  it("the 'how it works' guide", () => {
    render(
      <OnboardingGuideModal
        eyebrow="mystery mix club"
        heading="music is better with friends."
        intro="here's how it works."
        steps={[
          { title: "start a club", description: "make a home.", complete: true },
          { title: "invite friends", description: "share the link.", complete: false },
        ]}
        primaryLabel="create a club"
        onPrimary={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expectPaperModal();
  });

  it("what's new", () => {
    render(<ReleaseNotesModal onDismiss={vi.fn()} />);
    expectPaperModal();
  });

  it("report content", () => {
    render(<ReportContentModal contentPreview="a note" onSubmit={vi.fn()} onDismiss={vi.fn()} />);
    expectPaperModal();
  });
});
