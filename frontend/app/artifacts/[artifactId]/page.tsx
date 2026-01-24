'use client';

import { useParams } from 'next/navigation';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@radix-ui/react-tabs';
import { Button } from '@/components/ui/button';
import { Download, Share2, FileText, Book, Layout, MessageSquare } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export default function ArtifactPreviewPage() {
  const params = useParams();
  const artifactId = params.artifactId;

  return (
    <div className="min-h-screen bg-honey-50">
      <div className="max-w-6xl mx-auto py-10 px-4">
        <header className="flex flex-col md:flex-row md:items-center justify-between mb-8 space-y-4 md:space-y-0">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <Badge className="bg-honey-500 text-white font-black">HONEY PROCESSED</Badge>
              <span className="text-sm text-amber-600 font-bold uppercase tracking-widest">ID: {artifactId?.slice(0, 8)}</span>
            </div>
            <h1 className="text-4xl font-black text-amber-900 leading-tight">Economics 101: Market Dynamics</h1>
          </div>
          <div className="flex space-x-3">
            <Button variant="outline" className="border-honey-300 text-honey-700 hover:bg-honey-100 rounded-full font-bold">
              <Share2 className="mr-2 h-4 w-4" /> Share
            </Button>
            <Button className="bg-honey-500 hover:bg-honey-600 text-white rounded-full font-bold px-6 shadow-md">
              <Download className="mr-2 h-4 w-4" /> Download All
            </Button>
          </div>
        </header>

        <Tabs defaultValue="notes" className="space-y-6">
          <TabsList className="bg-white p-1 rounded-2xl border-2 border-honey-200 flex flex-wrap shadow-sm">
            <TabsTrigger value="notes" className="flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl font-bold text-amber-700 data-[state=active]:bg-honey-500 data-[state=active]:text-white transition-all">
              <FileText className="h-4 w-4" /> <span>Study Notes</span>
            </TabsTrigger>
            <TabsTrigger value="flashcards" className="flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl font-bold text-amber-700 data-[state=active]:bg-honey-500 data-[state=active]:text-white transition-all">
              <Layout className="h-4 w-4" /> <span>Flashcards</span>
            </TabsTrigger>
            <TabsTrigger value="quiz" className="flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl font-bold text-amber-700 data-[state=active]:bg-honey-500 data-[state=active]:text-white transition-all">
              <Book className="h-4 w-4" /> <span>Practice Quiz</span>
            </TabsTrigger>
            <TabsTrigger value="chat" className="flex-1 flex items-center justify-center space-x-2 py-3 px-4 rounded-xl font-bold text-amber-700 data-[state=active]:bg-honey-500 data-[state=active]:text-white transition-all">
              <MessageSquare className="h-4 w-4" /> <span>BeeChat</span>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="notes" className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            <Card className="p-10 border-2 border-honey-200 bg-white shadow-xl rounded-3xl min-h-[600px] prose prose-amber max-w-none">
              <h2 className="text-3xl font-black text-amber-900 border-b-4 border-honey-400 pb-2 mb-8 inline-block">Lecture Summary</h2>
              
              <div className="space-y-8">
                <section>
                  <h3 className="text-xl font-bold text-amber-800 flex items-center">
                    <div className="w-8 h-8 rounded-full bg-honey-100 flex items-center justify-center mr-3 text-honey-600 font-black">1</div>
                    Supply and Demand Equilibrium
                  </h3>
                  <p className="text-amber-900 leading-relaxed ml-11">
                    The fundamental model of market pricing in microeconomics. In a competitive market, the unit price for a particular good varies until it settles at a point where the quantity demanded equals the quantity supplied.
                  </p>
                </section>

                <section>
                  <h3 className="text-xl font-bold text-amber-800 flex items-center">
                    <div className="w-8 h-8 rounded-full bg-honey-100 flex items-center justify-center mr-3 text-honey-600 font-black">2</div>
                    Price Elasticity
                  </h3>
                  <p className="text-amber-900 leading-relaxed ml-11">
                    A measure used in economics to show the responsiveness, or elasticity, of the quantity demanded of a good or service to a change in its price when nothing but the price changes.
                  </p>
                  <ul className="ml-11 mt-4 space-y-2 list-disc text-amber-800">
                    <li><strong>Inelastic:</strong> Change in price results in small change in quantity (e.g., medicine).</li>
                    <li><strong>Elastic:</strong> Change in price results in large change in quantity (e.g., luxury cars).</li>
                  </ul>
                </section>
                
                <div className="p-6 bg-honey-50 rounded-2xl border-l-8 border-honey-500 italic text-amber-900 font-medium">
                  "Economics is not just about numbers; it's about the stories behind why people make the choices they do." - Professor Honeycomb
                </div>
              </div>
            </Card>
          </TabsContent>

          <TabsContent value="flashcards">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <Card key={i} className="aspect-[4/3] flex flex-col items-center justify-center p-8 text-center border-2 border-honey-200 hover:border-honey-500 transition-all cursor-pointer group bg-white shadow-md rounded-2xl">
                  <p className="text-xs font-black text-honey-500 mb-2 uppercase tracking-widest">Flashcard {i}</p>
                  <h3 className="text-xl font-bold text-amber-900 group-hover:scale-105 transition-transform">
                    {i === 1 ? 'What is the Law of Demand?' : 'Concept #' + i}
                  </h3>
                  <p className="mt-4 text-sm text-amber-600 font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                    Click to flip and see the answer
                  </p>
                </Card>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="quiz">
             <Card className="p-8 border-2 border-honey-200 bg-white shadow-lg text-center">
                <h3 className="text-2xl font-bold text-amber-900 mb-4">Quiz Mode Coming Soon!</h3>
                <p className="text-amber-700 mb-6">Our worker bees are busy finalizing the interactive quiz engine.</p>
                <div className="animate-pulse h-2 bg-honey-100 rounded-full w-48 mx-auto overflow-hidden">
                  <div className="h-full bg-honey-500 w-3/4"></div>
                </div>
             </Card>
          </TabsContent>

          <TabsContent value="chat">
             <Card className="p-0 border-2 border-honey-200 bg-white shadow-lg rounded-3xl overflow-hidden h-[600px] flex flex-col">
                <div className="bg-honey-500 p-4 text-white flex items-center space-x-3">
                  <div className="w-10 h-10 bg-white rounded-full flex items-center justify-center text-xl">🐝</div>
                  <div>
                    <h3 className="font-black">Professor Buzz</h3>
                    <p className="text-xs text-honey-50 font-bold">Ask me anything about the lecture!</p>
                  </div>
                </div>
                <div className="flex-1 p-6 space-y-4 overflow-y-auto bg-amber-50/30">
                  <div className="flex justify-start">
                    <div className="bg-white p-4 rounded-2xl rounded-tl-none shadow-sm max-w-[80%] border border-honey-100">
                      <p className="text-amber-900 font-medium">Hello! I've analyzed your lecture on Economics. What would you like to dive deeper into today?</p>
                    </div>
                  </div>
                </div>
                <div className="p-4 bg-white border-t-2 border-honey-100">
                  <div className="flex space-x-2">
                    <input 
                      type="text" 
                      placeholder="Ask the hive..." 
                      className="flex-1 bg-honey-50 border-2 border-honey-100 rounded-full px-6 py-3 focus:outline-none focus:border-honey-400 font-medium text-amber-900"
                    />
                    <Button className="bg-honey-500 hover:bg-honey-600 text-white rounded-full h-12 w-12 p-0 shadow-md">
                      <ArrowRight className="h-5 w-5" />
                    </Button>
                  </div>
                </div>
             </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

// Reuse the ArrowRight icon
import { ArrowRight as ArrowRightIcon } from 'lucide-react';
function ArrowRight(props: any) {
  return <ArrowRightIcon {...props} />
}
