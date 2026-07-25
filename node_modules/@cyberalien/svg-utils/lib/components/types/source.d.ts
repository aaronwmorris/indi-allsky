import { IconViewBox } from "../../svg/viewbox/types.js";
import { IconStatesList } from "../../svg-css/states/types.js";
import { SVGCSSStatefulIcon } from "../../svg-css/icon/types.js";
import { IconFallbackTemplate } from "../../svg-css/states/fallback/types.js";
import { StatefulIconSelectorsContext } from "../../svg-css/states/selector/types.js";
/**
 * Generated data for stateful icon
 */
interface StatefulComponentFactorySource {
  fallback?: IconFallbackTemplate;
  allStates: IconStatesList;
  supportedStates: Set<string>;
  staticClassname?: string;
  defaultStateValues: Record<string, string | boolean>;
  supportedStateValues: Record<string, string | boolean>;
  context: StatefulIconSelectorsContext;
}
/**
 * Content for component factory
 */
interface ComponentFactorySource extends Omit<SVGCSSStatefulIcon, 'viewBox' | 'fallback' | 'states'> {
  viewBox: IconViewBox;
  defaultFallback?: string;
  statefulData?: StatefulComponentFactorySource;
}
export { ComponentFactorySource, StatefulComponentFactorySource };