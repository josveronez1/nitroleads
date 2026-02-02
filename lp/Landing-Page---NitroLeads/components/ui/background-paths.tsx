
"use client";

import React from "react";
import { motion } from "framer-motion";
import { Button } from "./button";

function FloatingPaths({ position }: { position: number }) {
    const paths = Array.from({ length: 36 }, (_, i) => ({
        id: i,
        d: `M-${380 - i * 5 * position} -${189 + i * 6}C-${
            380 - i * 5 * position
        } -${189 + i * 6} -${312 - i * 5 * position} ${216 - i * 6} ${
            152 - i * 5 * position
        } ${343 - i * 6}C${616 - i * 5 * position} ${470 - i * 6} ${
            684 - i * 5 * position
        } ${875 - i * 6} ${684 - i * 5 * position} ${875 - i * 6}`,
        color: `rgba(13,110,253,${0.05 + i * 0.02})`,
        width: 0.5 + i * 0.03,
    }));

    return (
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
            <svg
                className="w-full h-full text-[#0D6EFD]"
                viewBox="0 0 696 316"
                fill="none"
            >
                <title>Background Paths</title>
                {paths.map((path) => (
                    <motion.path
                        key={path.id}
                        d={path.d}
                        stroke="currentColor"
                        strokeWidth={path.width}
                        strokeOpacity={0.05 + path.id * 0.02}
                        initial={{ pathLength: 0.3, opacity: 0.6 }}
                        animate={{
                            pathLength: 1,
                            opacity: [0.2, 0.5, 0.2],
                            pathOffset: [0, 1, 0],
                        }}
                        transition={{
                            duration: 15 + Math.random() * 10,
                            repeat: Number.POSITIVE_INFINITY,
                            ease: "linear",
                        }}
                    />
                ))}
            </svg>
        </div>
    );
}

export function BackgroundPaths({
    title = "Ative o Modo Nitro",
    subtitle = "Pronto para falar com quem realmente decide?",
    buttonText = "Acessar Decisores Agora"
}: {
    title?: string;
    subtitle?: string;
    buttonText?: string;
}) {
    // Split title by words for a cleaner layout that matches the user's image
    const words = title.split(" ");
    
    // Determine how to split words into two lines for impact
    const line1 = words.slice(0, words.length > 1 ? words.length - 1 : 1).join(" ");
    const line2 = words.length > 1 ? words[words.length - 1] : "";

    return (
        <div className="relative min-h-[70vh] w-full flex items-center justify-center overflow-hidden bg-white py-20">
            <div className="absolute inset-0">
                <FloatingPaths position={1} />
                <FloatingPaths position={-1} />
            </div>

            <div className="relative z-10 container mx-auto px-4 md:px-6 text-center">
                <motion.div
                    initial={{ opacity: 0, y: 30 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 1 }}
                    className="max-w-4xl mx-auto"
                >
                    <h2 className="text-6xl sm:text-7xl md:text-[100px] font-[900] text-[#212529] mb-6 tracking-tighter uppercase italic leading-[0.9] flex flex-col items-center">
                        <span className="block py-2 px-4 whitespace-nowrap">
                            {line1}
                        </span>
                        {line2 && (
                            <span className="block py-2 px-4 whitespace-nowrap">
                                {line2}
                            </span>
                        )}
                    </h2>

                    <motion.p 
                        initial={{ opacity: 0 }}
                        whileInView={{ opacity: 1 }}
                        viewport={{ once: true }}
                        transition={{ delay: 0.4 }}
                        className="text-lg md:text-xl text-gray-500 mb-10 font-medium max-w-xl mx-auto leading-relaxed"
                    >
                        {subtitle}
                    </motion.p>

                    <motion.div
                        initial={{ opacity: 0, scale: 0.9 }}
                        whileInView={{ opacity: 1, scale: 1 }}
                        viewport={{ once: true }}
                        transition={{ delay: 0.6 }}
                        className="inline-block group"
                    >
                        <Button
                            onClick={() => window.open('https://nitroleads.online', '_blank')}
                            className="nitro-gradient rounded-[14px] px-10 py-7 text-lg font-black 
                            text-white transition-all duration-300 shadow-xl shadow-blue-500/30
                            hover:shadow-blue-500/50 hover:-translate-y-1 uppercase italic tracking-wider flex items-center gap-2"
                        >
                            {buttonText}
                            <span className="group-hover:translate-x-1 transition-transform">→</span>
                        </Button>
                    </motion.div>
                </motion.div>
            </div>
        </div>
    );
}
