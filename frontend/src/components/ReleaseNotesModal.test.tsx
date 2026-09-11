import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReleaseNotesModal } from "./ReleaseNotesModal";
import { RELEASE_NOTES, formatReleaseDate } from "../data/releaseNotes";

describe("ReleaseNotesModal", () => {
  it("renders every entry's date as a group title and its items as a list", () => {
    render(<ReleaseNotesModal onDismiss={vi.fn()} />);

    for (const entry of RELEASE_NOTES) {
      expect(screen.getByText(formatReleaseDate(entry.date))).toBeInTheDocument();
      for (const item of entry.items) {
        expect(screen.getByText(item)).toBeInTheDocument();
      }
    }
  });

  it("calls onDismiss when the close button is clicked", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<ReleaseNotesModal onDismiss={onDismiss} />);

    await user.click(screen.getByRole("button", { name: "close" }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss when 'got it' is clicked", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<ReleaseNotesModal onDismiss={onDismiss} />);

    await user.click(screen.getByRole("button", { name: "got it" }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("is an accessible dialog labelled by its heading", () => {
    render(<ReleaseNotesModal onDismiss={vi.fn()} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("What's new");
  });
});
