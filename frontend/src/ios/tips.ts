import { Capacitor, registerPlugin } from "@capacitor/core";

/** A tip option as StoreKit reports it -- real localized price, no hardcoded
 *  currency formatting needed on the JS side. */
export type TipProduct = {
  id: string;
  displayName: string;
  displayPrice: string;
};

export type PurchaseResult = { status: "success" | "cancelled" | "pending" };

interface NativeTipsPlugin {
  getProducts(): Promise<{ products: TipProduct[] }>;
  purchase(options: { productId: string }): Promise<PurchaseResult>;
}

export const nativeTipsAvailable = () =>
  Capacitor.getPlatform() === "ios" && Capacitor.isPluginAvailable("MMCTips");

export const tips = registerPlugin<NativeTipsPlugin>("MMCTips");

function errorCode(error: unknown): string {
  return typeof error === "object" && error !== null && "code" in error
    ? String((error as { code: unknown }).code)
    : "";
}

export function tipErrorMessage(error: unknown): string {
  switch (errorCode(error)) {
    case "PRODUCTS_FAILED":
      return "couldn't load tip options. try again shortly.";
    case "PRODUCT_NOT_FOUND":
      return "that tip option isn't available right now.";
    case "UNVERIFIED":
      return "couldn't verify the purchase. try again.";
    case "PURCHASE_FAILED":
      return "the tip couldn't go through. try again.";
    default:
      return "something went wrong. try again.";
  }
}
