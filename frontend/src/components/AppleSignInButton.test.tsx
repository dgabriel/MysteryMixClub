import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppleSignInButton } from "./AppleSignInButton";

describe("AppleSignInButton", () => {
  it("renders a button that calls onClick", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<AppleSignInButton onClick={onClick} />);

    const button = screen.getByRole("button", { name: /sign in with apple/i });
    await user.click(button);

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
