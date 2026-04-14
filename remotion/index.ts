import { registerComposition } from 'remotion';
import { AIComposition } from './Composition';

registerComposition('AI_STUDIO_VIDEO', {
  component: AIComposition,
  durationInFrames: 300, // 10 seconds @ 30fps
  fps: 30,
  width: 1920,
  height: 1080,
  defaultProps: {
    elements: [],
  },
});
