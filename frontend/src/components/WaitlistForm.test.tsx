import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WaitlistForm } from "./WaitlistForm";
import { ApiError, joinWaitlist } from "../services/api";

// Mock only the API module; keep ApiError real so instanceof works.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return { ...actual, joinWaitlist: vi.fn() };
});

const mockJoin = vi.mocked(joinWaitlist);

describe("WaitlistForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("submits the trimmed email and shows a confirmation on success", async () => {
    mockJoin.mockResolvedValue({
      id: "wl-1",
      email: "fan@example.com",
      created_at: "2026-07-21T00:00:00Z",
      invited_at: null,
      invited_by: null,
    });
    const user = userEvent.setup();
    render(<WaitlistForm />);

    await user.type(screen.getByLabelText(/^email$/i), "  fan@example.com  ");
    await user.click(screen.getByRole("button", { name: /^join$/i }));

    expect(mockJoin).toHaveBeenCalledWith("fan@example.com");
    expect(await screen.findByText(/you're on the waitlist/i)).toBeInTheDocument();
    // The form itself is gone, replaced by the confirmation.
    expect(screen.queryByRole("button", { name: /^join$/i })).not.toBeInTheDocument();
  });

  it("shows a specific message on a duplicate email (409)", async () => {
    mockJoin.mockRejectedValue(new ApiError(409, "that email is already on the waitlist"));
    const user = userEvent.setup();
    render(<WaitlistForm />);

    await user.type(screen.getByLabelText(/^email$/i), "dup@example.com");
    await user.click(screen.getByRole("button", { name: /^join$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "that email is already on the waitlist.",
    );
  });

  it("shows a specific message when the backend rejects the format (422)", async () => {
    // A genuinely malformed string ("not-an-email") never reaches this
    // handler at all — the input's native type="email" constraint blocks
    // submission before any onSubmit fires. This exercises the 422 branch
    // for whatever edge case the browser's looser check lets through but
    // the backend's EmailStr validation still catches.
    mockJoin.mockRejectedValue(new ApiError(422, "invalid"));
    const user = userEvent.setup();
    render(<WaitlistForm />);

    await user.type(screen.getByLabelText(/^email$/i), "edge@example.com");
    await user.click(screen.getByRole("button", { name: /^join$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "that doesn't look like an email.",
    );
  });

  it("shows a calm generic message on any other failure", async () => {
    mockJoin.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    render(<WaitlistForm />);

    await user.type(screen.getByLabelText(/^email$/i), "user@example.com");
    await user.click(screen.getByRole("button", { name: /^join$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "couldn't join the waitlist. try again.",
    );
  });

  it("does not submit on an empty or whitespace-only email", async () => {
    const user = userEvent.setup();
    render(<WaitlistForm />);

    await user.click(screen.getByRole("button", { name: /^join$/i }));
    expect(mockJoin).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^email$/i), "   ");
    await user.click(screen.getByRole("button", { name: /^join$/i }));
    expect(mockJoin).not.toHaveBeenCalled();
  });
});
