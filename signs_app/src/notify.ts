/** Thin wrappers around Mantine's notifications service. Keeps callsites
 *  short and color-coded consistently. */
import { notifications } from "@mantine/notifications";

/** Show an error toast. Accepts an Error, a string, or anything stringifiable. */
export function notifyError(err: unknown, title = "Feil"): void {
  const message = err instanceof Error ? err.message : String(err);
  notifications.show({
    color: "red",
    title,
    message,
    autoClose: 8000,
  });
}

export function notifySuccess(message: string, title?: string): void {
  notifications.show({
    color: "green",
    title,
    message,
    autoClose: 4000,
  });
}

export function notifyInfo(message: string, title?: string): void {
  notifications.show({
    color: "blue",
    title,
    message,
    autoClose: 4000,
  });
}
