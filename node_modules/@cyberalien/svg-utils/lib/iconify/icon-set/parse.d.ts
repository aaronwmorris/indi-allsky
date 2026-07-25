import { ParseIconifyIconSetCallback } from "./types.js";
import { IconifyJSON } from "@iconify/types";
/**
 * Parse Iconify icon set and call callback for each icon
 */
declare function parseIconifyIconSet(data: IconifyJSON, callback: ParseIconifyIconSetCallback): void;
export { parseIconifyIconSet };