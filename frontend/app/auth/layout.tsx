export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-cream flex items-center justify-center p-4 font-sans selection:bg-honey selection:text-bee-black relative overflow-hidden">
      {/* Video Background */}
      <video 
        autoPlay 
        muted 
        loop 
        playsInline 
        preload="auto"
        className="absolute inset-0 w-full h-full object-cover opacity-20"
        style={{
          objectFit: 'cover',
          width: '100%',
          height: '100%'
        }}
      >
        <source src="/assets/hero-bg.mp4" type="video/mp4" />
      </video>
      
      <div className="absolute inset-0 z-0 opacity-20 pointer-events-none overflow-hidden">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-honey rounded-full blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-honey rounded-full blur-[120px]" />
      </div>
      <div className="relative z-10 w-full max-w-md">
        {children}
      </div>
    </div>
  );
}
