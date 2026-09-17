import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReportContentModal } from "./ReportContentModal";
import { ApiError } from "../services/api";

function renderModal(overrides: Partial<Parameters<typeof ReportContentModal>[0]> = {}) {
  return render(
    <ReportContentModal
      contentPreview="this is spam"
      onSubmit={vi.fn().mockResolvedValue(undefined)}
      onDismiss={vi.fn()}
      {...overrides}
    />,
  );
}

describe("ReportContentModal (MysteryMixClub-4vii.13)", () => {
  it("is an accessible dialog showing the reported content and every reason option", () => {
    renderModal();

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("report content");
    expect(screen.getByText("this is spam", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "inappropriate content" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "harassment" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "spam" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "other" })).toBeInTheDocument();
  });

  it("disables submit until a reason is picked", async () => {
    const user = userEvent.setup();
    renderModal();

    expect(screen.getByRole("button", { name: "submit report" })).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "spam" }));

    expect(screen.getByRole("button", { name: "submit report" })).toBeEnabled();
  });

  it("submits the picked reason and trimmed detail", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderModal({ onSubmit });

    await user.click(screen.getByRole("radio", { name: "harassment" }));
    await user.type(screen.getByRole("textbox", { name: /details/i }), "  rude comment  ");
    await user.click(screen.getByRole("button", { name: "submit report" }));

    expect(onSubmit).toHaveBeenCalledWith("harassment", "rude comment");
  });

  it("shows a calm error message and re-enables submit if onSubmit rejects", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockRejectedValue(new ApiError(500, "server exploded"));
    renderModal({ onSubmit });

    await user.click(screen.getByRole("radio", { name: "other" }));
    await user.click(screen.getByRole("button", { name: "submit report" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("server exploded");
    expect(screen.getByRole("button", { name: "submit report" })).toBeEnabled();
  });

  it("calls onDismiss when the close button is clicked, or Escape is pressed", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderModal({ onDismiss });

    await user.click(screen.getByRole("button", { name: /dismiss report dialog/i }));
    expect(onDismiss).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onDismiss).toHaveBeenCalledTimes(2);
  });

  it("calls onDismiss when cancel is clicked", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderModal({ onDismiss });

    await user.click(screen.getByRole("button", { name: "cancel" }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
