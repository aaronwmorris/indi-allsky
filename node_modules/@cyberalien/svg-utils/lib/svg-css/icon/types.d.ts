import { CSSKeyframes, CSSRules } from "../../css/types.js";
import { IconViewBox } from "../../svg/viewbox/types.js";
import { IconStatesList } from "../states/types.js";
/**
 * Main properties
 */
interface MainProps {
  viewBox: IconViewBox | string;
  fallback?: string;
  content: string;
}
interface StatefulMainProps extends MainProps {
  states?: IconStatesList;
}
/**
 * CSS data
 */
interface SVGCSSIconRules {
  classes?: Record<string, CSSRules | string>;
  animations?: Record<string, CSSRules | string>;
  keyframes?: Record<string, CSSKeyframes | string>;
}
/**
 * Extended class interface for stateful icons
 */
interface ExtendedSVGCSSIconClass {
  stateRules?: Record<string, CSSRules | string>;
  transition?: CSSRules | string;
  stateTransition?: Record<string, CSSRules | string>;
}
/**
 * Stateful CSS data
 */
interface SVGCSSStatefulIconRules extends SVGCSSIconRules {
  statefulClasses?: Record<string, ExtendedSVGCSSIconClass>;
}
/**
 * Icon data
 */
interface SVGCSSIcon extends MainProps, SVGCSSIconRules {}
/**
 * Icon with states
 */
interface SVGCSSStatefulIcon extends StatefulMainProps, SVGCSSStatefulIconRules {}
export { ExtendedSVGCSSIconClass, SVGCSSIcon, SVGCSSIconRules, SVGCSSStatefulIcon, SVGCSSStatefulIconRules };