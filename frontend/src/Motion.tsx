import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

export function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const change = () => setReduced(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  return reduced;
}

/** Keep exits mounted, but let a rapid reopen cancel the exit immediately. */
export function Presence({
  show,
  children,
}: {
  show: boolean;
  children: (leaving: boolean) => ReactNode;
}) {
  const [mounted, setMounted] = useState(show);
  const reduced = useReducedMotion();
  useEffect(() => {
    if (show) {
      setMounted(true);
      return;
    }
    const timer = setTimeout(() => setMounted(false), reduced ? 0 : 180);
    return () => clearTimeout(timer);
  }, [show, reduced]);
  return show || mounted ? children(!show) : null;
}

export function ModalLayer({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const scope = root.current;
    const focusable = () =>
      Array.from(
        scope?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
        ) ?? [],
      ).filter((el) => el.getClientRects().length && !el.closest("[inert]"));
    // Prevent clicks and keyboard focus from reaching the workspace underneath.
    const workspace = document.querySelector<HTMLElement>(".main-shell");
    const sidebar = document.querySelector<HTMLElement>(".sidebar");
    const prior = [workspace?.inert, sidebar?.inert];
    if (workspace) workspace.inert = true;
    if (sidebar) sidebar.inert = true;
    (
      scope?.querySelector<HTMLElement>("[data-autofocus]") ?? focusable()[0]
    )?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      const first = items[0],
        last = items.at(-1);
      if (!first) {
        event.preventDefault();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !scope?.contains(document.activeElement))
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !scope?.contains(document.activeElement))
      ) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      if (workspace) workspace.inert = prior[0] ?? false;
      if (sidebar) sidebar.inert = prior[1] ?? false;
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [open]);
  return (
    <Presence show={open}>
      {(leaving) => (
        <div
          ref={root}
          className={`modal-backdrop ${leaving ? "leaving" : ""}`}
          inert={leaving}
          aria-hidden={leaving || undefined}
          onClick={(event) => {
            if (event.target === event.currentTarget) close.current();
          }}
        >
          {children}
        </div>
      )}
    </Presence>
  );
}

/** Move a single highlight; do not remount the audio player to animate tabs. */
export function SlidingHighlight({
  active,
  className = "tab-highlight",
}: {
  active: string;
  className?: string;
}) {
  const marker = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const parent = marker.current?.parentElement;
    if (!parent) return;
    const update = () => {
      const target = parent.querySelector<HTMLElement>("button.active");
      if (!target || !marker.current) return;
      marker.current.style.width = `${target.offsetWidth}px`;
      marker.current.style.transform = `translateX(${target.offsetLeft}px)`;
      marker.current.style.opacity = "1";
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(parent);
    parent
      .querySelectorAll("button")
      .forEach((button) => observer.observe(button));
    return () => observer.disconnect();
  }, [active]);
  return <span ref={marker} className={className} aria-hidden="true" />;
}

export function usePressFeedback() {
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced) return;
    const running = new Set<Animation>();
    const press = (event: PointerEvent) => {
      if (event.button !== 0 || !(event.target instanceof Element)) return;
      const button = event.target.closest<HTMLElement>(
        ".button,.play-button,.icon-button,.mode-cards>button,.format-options>button",
      );
      if (!button || button.matches(":disabled") || button.closest("[inert]"))
        return;
      const rect = button.getBoundingClientRect();
      const ripple = document.createElement("span");
      ripple.className = "press-ripple";
      ripple.setAttribute("aria-hidden", "true");
      const size = Math.max(rect.width, rect.height) * 2;
      Object.assign(ripple.style, {
        width: `${size}px`,
        height: `${size}px`,
        left: `${event.clientX - rect.left - size / 2}px`,
        top: `${event.clientY - rect.top - size / 2}px`,
      });
      button.append(ripple);
      const animation = ripple.animate(
        [
          { transform: "scale(0)", opacity: 0.25 },
          { transform: "scale(1)", opacity: 0 },
        ],
        { duration: 560, easing: "cubic-bezier(.16,1,.3,1)" },
      );
      running.add(animation);
      const finish = () => {
        ripple.remove();
        running.delete(animation);
      };
      void animation.finished.then(finish, finish);
    };
    document.addEventListener("pointerdown", press, { passive: true });
    return () => {
      document.removeEventListener("pointerdown", press);
      running.forEach((animation) => animation.cancel());
    };
  }, [reduced]);
}

export function useDismissiblePopovers() {
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      document
        .querySelectorAll<HTMLDetailsElement>(".transcript-filters[open]")
        .forEach((menu) => {
          if (event.target instanceof Node && !menu.contains(event.target))
            menu.open = false;
        });
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const menu = document.querySelector<HTMLDetailsElement>(
        ".transcript-filters[open]",
      );
      if (menu) {
        menu.open = false;
        menu.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", outside, { passive: true });
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, []);
}

export function useContentArrival(
  ref: RefObject<HTMLElement | null>,
  change: string,
) {
  const reduced = useReducedMotion();
  useEffect(() => {
    if (reduced || !ref.current) return;
    const animation = ref.current.animate(
      [
        { opacity: 0.35, translate: "0 6px" },
        { opacity: 1, translate: "0 0" },
      ],
      { duration: 260, easing: "cubic-bezier(.16,1,.3,1)" },
    );
    return () => animation.cancel();
  }, [change, reduced, ref]);
}
