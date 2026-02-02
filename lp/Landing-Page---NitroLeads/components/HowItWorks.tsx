
import React from 'react';
import { Target, Users, TrendingUp } from 'lucide-react';

export const HowItWorks: React.FC = () => {
  const steps = [
    {
      icon: <Target className="w-8 h-8" />,
      title: "1. Segmente seu alvo",
      description: "Escolha o setor e a região onde seus melhores clientes estão. Utilize filtros avançados de CNAE e localização."
    },
    {
      icon: <Users className="w-8 h-8" />,
      title: "2. Identifique os Sócios",
      description: "Nossa tecnologia cruza dados para encontrar os donos e decisores. Chega de falar com intermediários."
    },
    {
      icon: <TrendingUp className="w-8 h-8" />,
      title: "3. Aborde e Venda",
      description: "Exporte listas com WhatsApp e e-mails validados prontos para prospecção direta. Resultados imediatos."
    }
  ];

  return (
    <section id="como-funciona" className="py-20 bg-[#F8F9FA]">
      <div className="container mx-auto px-4 md:px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-extrabold text-[#212529] mb-4">
            3 Passos para dominar seu mercado
          </h2>
          <p className="text-gray-500">Simples, rápido e focado em alta conversão.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-12 max-w-6xl mx-auto">
          {steps.map((step, idx) => (
            <div key={idx} className="relative group">
              <div className="bg-white p-8 rounded-[12px] shadow-sm hover:shadow-xl transition-all duration-300 border border-gray-100 flex flex-col items-center text-center">
                <div className="mb-6 p-4 bg-blue-50 text-[#0D6EFD] rounded-[12px] group-hover:scale-110 transition-transform">
                  {step.icon}
                </div>
                <h3 className="text-xl font-bold text-[#212529] mb-4">{step.title}</h3>
                <p className="text-gray-500 text-sm leading-relaxed">{step.description}</p>
              </div>
              {idx < 2 && (
                <div className="hidden lg:block absolute top-1/2 -right-6 translate-x-1/2 -translate-y-1/2">
                   <div className="w-12 h-1 bg-blue-100 rounded-full" />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
