import { AbsoluteFill, useVideoConfig, useCurrentFrame, interpolate, spring } from 'remotion';
import React from 'react';

export const AIComposition: React.FC<{ elements: any[] }> = ({ elements }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // Helper to get animation style by role
  const getStyle = (el: any) => {
    const startFrame = (el.index || 0) * 10; // Staggered appearance
    const progress = spring({
      frame: frame - startFrame,
      fps,
      config: { damping: 10 }
    });

    const baseStyle: React.CSSProperties = {
      position: 'absolute',
      left: `${(el.x / 420) * 100}%`,
      top: `${(el.y / 297) * 100}%`,
      width: `${(el.w / 420) * 100}%`,
      height: `${(el.h / 297) * 100}%`,
      opacity: progress,
    };

    if (el.role === 'headline') {
      const translateY = interpolate(progress, [0, 1], [20, 0]);
      return { ...baseStyle, transform: `translateY(${translateY}px)` };
    }
    
    if (el.role === 'photo') {
      const scale = interpolate(frame, [0, 300], [1, 1.1]);
      return { ...baseStyle, transform: `scale(${scale})` };
    }

    return baseStyle;
  };

  return (
    <AbsoluteFill style={{ backgroundColor: '#F8F8F8' }}>
      {elements.map((el, i) => {
        if (el.type === 'text' || el.type === 'textblock') {
           return (
             <div key={el.id} style={getStyle({ ...el, index: i })}>
               {el.content || el.text || "Sample Text"}
             </div>
           );
        }
        if (el.type === 'image') {
          return (
             <img 
               key={el.id} 
               src={el.href || el.base64} 
               style={getStyle({ ...el, index: i })}
               alt=""
             />
          );
        }
        return null;
      })}
    </AbsoluteFill>
  );
};
