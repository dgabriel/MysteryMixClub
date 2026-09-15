import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OnboardingGuideModal } from "./OnboardingGuideModal";

const STEPS = [
  { title: "step one", description: "first" },
  { title: "step two", description: "second", complete: true },
];

function renderModal(overrides: Partial<Parameters<typeof OnboardingGuideModal>[0]> = {}) {
  return render(
    <OnboardingGuideModal
      eyebrow="mystery mix club"
      heading="hello."
      intro="intro copy"
      steps={STEPS}
      primaryLabel="go"
      onPrimary={vi.fn()}
      onDismiss={vi.fn()}
      {...overrides}
    />,
  );
}

describe("OnboardingGuideModal", () => {
  it("is an accessible dialog labelled by its heading, with every step rendered", () => {
    renderModal();

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("hello.");
    expect(screen.getByText("step one")).toBeInTheDocument();
    expect(screen.getByText("step two")).toBeInTheDocument();
  });

  it("calls onDismiss when the close button is clicked", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderModal({ onDismiss });

    await user.click(screen.getByRole("button", { name: /dismiss welcome guide/i }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("calls onPrimary when the primary CTA is clicked", async () => {
    const user = userEvent.setup();
    const onPrimary = vi.fn();
    renderModal({ onPrimary, primaryLabel: "let's go" });

    await user.click(screen.getByRole("button", { name: "let's go" }));

    expect(onPrimary).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss on Escape", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderModal({ onDismiss });

    await user.keyboard("{Escape}");

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("moves focus into the dialog on mount", () => {
    renderModal();

    expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);
  });

  it("restores focus to whatever had it beforehand, on unmount", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "open";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { unmount } = renderModal();
    expect(document.activeElement).not.toBe(trigger);

    unmount();
    expect(document.activeElement).toBe(trigger);

    trigger.remove();
  });

  it("traps Tab focus: tabbing past the last focusable element wraps to the first", async () => {
    const user = userEvent.setup();
    renderModal();

    const dialog = screen.getByRole("dialog");
    const focusables = dialog.querySelectorAll("button");
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    last.focus();
    await user.tab();

    expect(document.activeElement).toBe(first);
  });

  it("shift+Tab from the first focusable element wraps to the last", async () => {
    const user = userEvent.setup();
    renderModal();

    const dialog = screen.getByRole("dialog");
    const focusables = dialog.querySelectorAll("button");
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    first.focus();
    await user.tab({ shift: true });

    expect(document.activeElement).toBe(last);
  });

  it("renders a checkmark instead of an ordinal for a completed step", () => {
    renderModal();

    // "step two" is marked complete -- its number badge carries a checkmark
    // svg rather than the literal digit "2".
    const stepTwoHeading = screen.getByText("step two");
    const badge = stepTwoHeading.closest("li")?.querySelector("svg");
    expect(badge).not.toBeNull();
  });
});
