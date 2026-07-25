import { IconStatesList } from "../types.js";
import { IconFallbackTemplate } from "./types.js";
/**
 * Parse fallback template string into array of strings and states
 */
declare function parseIconFallbackTemplate(fallback: string, states: IconStatesList): IconFallbackTemplate | undefined;
export { parseIconFallbackTemplate };