'use client';

import { useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, Line, Sphere } from '@react-three/drei';
import * as THREE from 'three';
import { useResolvedTheme } from '@/hooks/useResolvedTheme';

function Network() {
  const group = useRef<THREE.Group>(null);
  const isDark = useResolvedTheme() !== 'light';

  const color = isDark ? '#ffffff' : '#000000';
  const accentColor = isDark ? '#6366f1' : '#4f46e5';
  
  useFrame((state) => {
    if (group.current) {
      group.current.rotation.y = state.clock.elapsedTime * 0.05;
      group.current.rotation.z = Math.sin(state.clock.elapsedTime * 0.1) * 0.1;
    }
  });

  const numNodes = 12;
  const radius = 2;
  
  // Create nodes in a circle but offset them with some noise
  const points = Array.from({ length: numNodes }, (_, i) => {
    const angle = (i / numNodes) * Math.PI * 2;
    const x = Math.cos(angle) * radius;
    const y = Math.sin(angle * 2) * 0.5; // slight wave
    const z = Math.sin(angle) * radius;
    return new THREE.Vector3(x, y, z);
  });

  // Connect every node to its neighbor, and some cross-connections
  const lines = [];
  for (let i = 0; i < numNodes; i++) {
    lines.push([points[i], points[(i + 1) % numNodes]]);
    lines.push([points[i], points[(i + 3) % numNodes]]);
  }

  return (
    <group ref={group} rotation={[Math.PI * 0.2, 0, 0]}>
      <Float speed={1.5} rotationIntensity={0.5} floatIntensity={1}>
        {points.map((pos, i) => (
          <Sphere key={i} position={pos} args={[0.04, 16, 16]}>
            <meshBasicMaterial color={i % 3 === 0 ? accentColor : color} transparent opacity={0.8} />
          </Sphere>
        ))}
        {lines.map((pts, i) => (
          <Line 
            key={i} 
            points={pts as [THREE.Vector3, THREE.Vector3]} 
            color={color} 
            lineWidth={0.5} 
            transparent 
            opacity={0.15} 
          />
        ))}
      </Float>
    </group>
  );
}

export function HeroVisual() {
  return (
    <div className="absolute inset-0 -z-10 h-[600px] w-full pointer-events-none overflow-hidden opacity-60">
      {/* No lights and no environment map: every material here is unlit (`meshBasicMaterial`
          and drei's line material), so neither had any visual effect. The `Environment` preset
          also pulled an HDR file from a third-party CDN on every landing-page load. */}
      <Canvas camera={{ position: [0, 0, 5], fov: 45 }} dpr={[1, 2]}>
        <Network />
      </Canvas>
    </div>
  );
}
