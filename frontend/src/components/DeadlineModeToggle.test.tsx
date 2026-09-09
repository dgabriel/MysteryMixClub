import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DeadlineModeToggle } from "./DeadlineModeToggle";

describe("DeadlineModeToggle", () => {
  it("renders both options with the current value pressed", () => {
    render(<DeadlineModeToggle value="duration" onChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: "flexible window" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "weekly schedule" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("flips aria-pressed when value is weekly_anchor", () => {
    render(<DeadlineModeToggle value="weekly_anchor" onChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: "flexible window" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "weekly schedule" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("calls onChange with the clicked option's value", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DeadlineModeToggle value="duration" onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "weekly schedule" }));

    expect(onChange).toHaveBeenCalledWith("weekly_anchor");
  });

  it("disables both buttons when disabled is set", () => {
    render(<DeadlineModeToggle value="duration" onChange={vi.fn()} disabled />);

    expect(screen.getByRole("button", { name: "flexible window" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "weekly schedule" })).toBeDisabled();
  });

  // The active-tab indicator is the one thing that must actually be visible
  // (MysteryMixClub-ztbx — the prior plain-text treatment tested as easy to
  // miss), so the border/color swap is pinned, not just aria-pressed.
  it("gives the active tab the accent border and the inactive tab muted text (dark ramp)", () => {
    render(<DeadlineModeToggle value="duration" onChange={vi.fn()} />);

    const active = screen.getByRole("button", { name: "flexible window" });
    const inactive = screen.getByRole("button", { name: "weekly schedule" });
    expect(active.className).toMatch(/border-accent/);
    expect(active.className).toMatch(/text-foreground/);
    expect(inactive.className).toMatch(/border-transparent/);
    expect(inactive.className).toMatch(/text-muted-foreground/);
  });

  it("uses the ink ramp on paper", () => {
    render(<DeadlineModeToggle onPaper value="weekly_anchor" onChange={vi.fn()} />);

    const active = screen.getByRole("button", { name: "weekly schedule" });
    expect(active.className).toMatch(/border-ink-accent/);
    expect(active.className).toMatch(/text-ink\b/);
  });

  // MysteryMixClub-edsf: the toggle ships with an explanation of what the
  // choice does, rather than leaving callers to duplicate it (which is what
  // happened the first time — flagged by Flaught's own review of PR #287).
  it("explains what the two modes mean", () => {
    render(<DeadlineModeToggle value="duration" onChange={vi.fn()} />);

    expect(
      screen.getByText(/flexible window counts days from whenever a phase opens/),
    ).toBeInTheDocument();
  });
});
