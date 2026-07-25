import { IconStatesList } from "../types.js";
import { IconFallbackTemplate } from "./types.js";
/**
 * Parse and test fallback template string
 *
 * This will make sure template is valid and does not contain invalid characters
 */
declare function parseAndTestIconFallbackTemplate(fallback: string, states: IconStatesList): IconFallbackTemplate | undefined;
export { parseAndTestIconFallbackTemplate };