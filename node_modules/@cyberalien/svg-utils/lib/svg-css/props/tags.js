/**
* Tag used to set attribute value without animation duration
*/
const svgSetTag = "set";
/**
* Attribute animation tag
*/
const svgAnimationTag = "animate";
/**
* Tag for animating transformations in SVG
*/
const svgAnimateTransformTag = "animateTransform";
/**
* Tag for animating motion in SVG
*/
const svgAnimateMotionTag = "animateMotion";
/**
* All tags for animating SVG
*/
const svgAnimationTags = [
	"set",
	svgAnimationTag,
	svgAnimateTransformTag,
	svgAnimateMotionTag
];
export { svgAnimateMotionTag, svgAnimateTransformTag, svgAnimationTag, svgAnimationTags, svgSetTag };
