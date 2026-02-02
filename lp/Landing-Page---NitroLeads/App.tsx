
import React, { useState } from 'react';
import { Header } from './components/Header';
import { Hero } from './components/Hero';
import { TrustBar } from './components/TrustBar';
import { Comparison } from './components/Comparison';
import { ComparisonLightning } from './components/ComparisonLightning';
import { HowItWorks } from './components/HowItWorks';
import { Features } from './components/Features';
import { FAQ } from './components/FAQ';
import { Footer } from './components/Footer';
import { CTA } from './components/CTA';
import { Banner } from './components/ui/banner';
import { Zap, ArrowRight, Unlock } from 'lucide-react';
import { Button } from './components/ui/button';

const App: React.FC = () => {
  const [showBanner, setShowBanner] = useState(true);

  return (
    <div className="min-h-screen flex flex-col">
      <Banner
        show={showBanner}
        onHide={() => setShowBanner(false)}
        variant="premium"
        title="LIBERTE SEU TIME COMERCIAL"
        description="Pare de caçar decisores um por um. Receba listas validadas em segundos."
        icon={<Unlock className="w-4 h-4 text-white" />}
        showShade={true}
        closable={true}
        className="fixed top-0 left-0 right-0 z-[100]"
        action={
          <Button
            onClick={() => {
              const el = document.getElementById('cta');
              el?.scrollIntoView({ behavior: 'smooth' });
            }}
            size="sm"
            className="hidden md:flex items-center gap-1 bg-white text-[#0D6EFD] hover:bg-blue-50 font-black italic uppercase text-[10px] h-7 px-3 rounded-lg"
          >
            QUERO ESCALA
            <ArrowRight className="h-3 w-3" />
          </Button>
        }
      />
      <Header isBannerVisible={showBanner} />
      <main>
        <Hero isBannerVisible={showBanner} />
        <TrustBar />
        <Comparison />
        <ComparisonLightning />
        <HowItWorks />
        <Features />
        <FAQ />
        <CTA />
      </main>
      <Footer />
    </div>
  );
};

export default App;
