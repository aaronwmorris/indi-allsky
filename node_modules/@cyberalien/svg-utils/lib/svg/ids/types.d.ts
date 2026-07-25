import { UniqueHashPartialOptions } from "../../helpers/hash/types.js";
import { ParsedXMLTagElement } from "../../xml/types.js";
interface ChangeIDResult {
  map: Record<string, ParsedXMLTagElement[]>;
  usage: Record<string, ParsedXMLTagElement[]>;
}
type UniqueIDOptions = UniqueHashPartialOptions;
export { ChangeIDResult, UniqueIDOptions };