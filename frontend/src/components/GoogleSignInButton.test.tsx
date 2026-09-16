import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GoogleSignInButton } from "./GoogleSignInButton";

describe("GoogleSignInButton", () => {
  it("renders a real link when given href (web)", () => {
    render(<GoogleSignInButton href="https://api.test/auth/google/login" />);

    const link = screen.getByRole("link", { name: /sign in with google/i });
    expect(link).toHaveAttribute("href", "https://api.test/auth/google/login");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a button that calls onClick when given onClick (native)", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<GoogleSignInButton onClick={onClick} />);

    const button = screen.getByRole("button", { name: /sign in with google/i });
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    await user.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
