import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PushActivationPrompt } from "./PushActivationPrompt";
import {
  nativePushAvailable,
  onAppResume,
  pushPermissionStatus,
  requestPushPermissionAndRegister,
} from "../ios/push";
import { openNotificationSettings } from "../ios/appSettings";
import { MAX_PUSH_ASKS, recordPushAsk } from "../lib/pushAsk";

vi.mock("../ios/push", () => ({
  nativePushAvailable: vi.fn(),
  pushPermissionStatus: vi.fn(),
  requestPushPermissionAndRegister: vi.fn(),
  syncPushRegistration: vi.fn(),
  onAppResume: vi.fn(),
}));
vi.mock("../ios/appSettings", () => ({ openNotificationSettings: vi.fn() }));

const mockNative = vi.mocked(nativePushAvailable);
const mockStatus = vi.mocked(pushPermissionStatus);
const mockRequest = vi.mocked(requestPushPermissionAndRegister);
const mockOpenSettings = vi.mocked(openNotificationSettings);

describe("PushActivationPrompt (MysteryMixClub-gxh3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockNative.mockReturnValue(true);
    mockRequest.mockResolvedValue("granted");
    mockOpenSettings.mockResolvedValue(true);
    vi.mocked(onAppResume).mockReturnValue(() => {});
  });

  it("never asked by iOS: explains first, then 'turn on' fires the system prompt", async () => {
    mockStatus.mockResolvedValue("prompt");
    const user = userEvent.setup();
    render(<PushActivationPrompt userId="u1" />);

    expect(
      await screen.findByRole("dialog", { name: /never miss your turn/i }),
    ).toBeInTheDocument();
    expect(mockRequest).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /turn on notifications/i }));
    expect(mockRequest).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("denied: offers iOS settings instead of a prompt iOS won't show", async () => {
    mockStatus.mockResolvedValue("denied");
    const user = userEvent.setup();
    render(<PushActivationPrompt userId="u1" />);

    await user.click(await screen.findByRole("button", { name: /open ios settings/i }));
    expect(mockOpenSettings).toHaveBeenCalledOnce();
    expect(mockRequest).not.toHaveBeenCalled();
  });

  it("'not now' just closes, and counts as one of the three asks", async () => {
    mockStatus.mockResolvedValue("prompt");
    const user = userEvent.setup();
    const { unmount } = render(<PushActivationPrompt userId="u1" />);

    await user.click(await screen.findByRole("button", { name: /not now/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    unmount();

    // Reopening the same day doesn't ask again.
    render(<PushActivationPrompt userId="u1" />);
    await waitFor(() => expect(mockStatus).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says nothing when push is already granted, on web, or after three asks", async () => {
    mockStatus.mockResolvedValue("granted");
    const first = render(<PushActivationPrompt userId="u1" />);
    await waitFor(() => expect(mockStatus).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    first.unmount();

    mockNative.mockReturnValue(false);
    const second = render(<PushActivationPrompt userId="u1" />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    second.unmount();

    mockNative.mockReturnValue(true);
    mockStatus.mockResolvedValue("prompt");
    for (let i = 0; i < MAX_PUSH_ASKS; i++) recordPushAsk("u2", 0);
    render(<PushActivationPrompt userId="u2" />);
    await waitFor(() => expect(mockStatus).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
