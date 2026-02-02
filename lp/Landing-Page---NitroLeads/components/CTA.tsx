
import React from 'react';
import { BackgroundPaths } from './ui/background-paths';

export const CTA: React.FC = () => {
  return (
    <section id="cta">
      <BackgroundPaths 
        title="Liberte-se do Manual" 
        subtitle="Pare de caçar. Comece a fechar. O NitroLeads entrega o quadro societário inteiro na sua mão em segundos."
        buttonText="QUERO ME LIBERTAR AGORA"
      />
    </section>
  );
};
