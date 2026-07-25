import { ParsedIconifyIcon } from "./types.js";
import { IconifyIcon } from "@iconify/types";
/**
 * Normalise icon: apply transformations
 */
declare function normaliseIconifyIcon(data: IconifyIcon): ParsedIconifyIcon;
export { normaliseIconifyIcon };