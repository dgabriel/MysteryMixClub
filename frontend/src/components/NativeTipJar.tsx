import { useEffect, useState } from "react";
import { Button } from "./Button";
import { tips, tipErrorMessage, type TipProduct } from "../ios/tips";

/**
 * Native iOS tip jar (MysteryMixClub-4vii.15) -- Apple In-App Purchase
 * consumables, replacing the web app's Venmo link on iOS. An external
 * payment link is a real App Store Guideline 3.1.1 risk; StoreKit
 * consumables are the App Store-native equivalent. Tips are voluntary and
 * unlock nothing -- no club limits, votes, submissions, or status change
 * based on whether or how much a member has tipped.
 *
 * Renders nothing while products are loading or if StoreKit couldn't load
 * them (fails quietly rather than showing a broken tip jar) -- this is a
 * voluntary nicety, not something worth surfacing an error state over.
 */
export function NativeTipJar() {
  const [products, setProducts] = useState<TipProduct[] | null>(null);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [purchasingId, setPurchasingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    tips
      .getProducts()
      .then(({ products: fetched }) => {
        if (!cancelled) setProducts(fetched);
      })
      .catch(() => {
        if (!cancelled) setProducts([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function purchase(product: TipProduct) {
    setPurchasingId(product.id);
    setStatus("idle");
    setErrorMessage(null);
    try {
      const result = await tips.purchase({ productId: product.id });
      if (result.status === "success") {
        setStatus("success");
      }
      // "cancelled" and "pending" are normal outcomes, not errors -- no
      // message needed for either.
    } catch (err) {
      setStatus("error");
      setErrorMessage(tipErrorMessage(err));
    } finally {
      setPurchasingId(null);
    }
  }

  if (!products || products.length === 0) return null;

  return (
    <div className="mt-3">
      <div className="flex flex-wrap gap-2">
        {products.map((product) => (
          <Button
            key={product.id}
            type="button"
            variant="ghost"
            onPaper
            onClick={() => void purchase(product)}
            disabled={purchasingId !== null}
          >
            {purchasingId === product.id ? "sending…" : `${product.displayName} · ${product.displayPrice}`}
          </Button>
        ))}
      </div>
      <p className="mt-2 text-mini leading-[1.5] text-ink-muted">
        tips are optional and don&apos;t unlock any features.
      </p>
      {status === "success" ? (
        <p role="status" className="mt-2 text-mini text-ink-accent">
          thank you!
        </p>
      ) : null}
      {status === "error" && errorMessage ? (
        <p role="alert" className="mt-2 text-mini text-destructive-text">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
