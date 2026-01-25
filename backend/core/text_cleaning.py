import re
import os
import logging
import google.generativeai as genai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class TextCleaningService:
    def __init__(self):
        self._setup_gemini()

    def _setup_gemini(self):
        """Initialize Gemini client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-flash-latest')
        else:
            logger.warning("GEMINI_API_KEY not found. LLM cleaning will be skipped.")
            self.model = None

    def clean_regex(self, text: str) -> str:
        """
        Performs fast, rule-based cleaning using Regex.
        - Removes timestamps (e.g. 0:00, 1:05:20).
        - Removes speaker labels (e.g. BRANDON:, STUDENT:).
        - Removes parentheticals/stage directions (e.g. (laughing)).
        - Remove filler words + normalize whitespace.
        """
        if not text:
            return ""

        # 1. Remove Timestamps (e.g. 0:00, 12:30, 1:05:00) on their own line or inline
        text = re.sub(r'\b\d{1,2}:\d{2}(:\d{2})?\b', '', text)

        # 2. Remove Speaker Labels (e.g. BRANDON:, STUDENT:)
        # Looking for UPPERCASE words followed by colon at start of line or sentence
        text = re.sub(r'\b[A-Z]+:\s*', '', text)

        # 3. Remove Parentheticals/Stage Directions (e.g. (laughing), [inaudible])
        text = re.sub(r'\([^\)]+\)', '', text)
        text = re.sub(r'\[[^\]]+\]', '', text)

        # 4. Normalize whitespace (tabs/newlines -> space, multiple spaces -> single)
        text = re.sub(r'\s+', ' ', text).strip()

        # 5. Remove filler words (case-insensitive, standalone)
        fillers = [r'\bum\b', r'\buh\b', r'\bah\b', r'\ber\b', r'\bhmm\b']
        for filler in fillers:
            text = re.sub(filler, '', text, flags=re.IGNORECASE)

        # 6. Handle "like" specifically
        text = re.sub(r'\blike\s+', ' ', text, flags=re.IGNORECASE)

        # 7. Fix punctuation
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        text = re.sub(r'\.+', '.', text)

        return text.strip()

    def clean_with_gemini(self, text: str) -> str:
        """
        Uses Gemini to fix transcription errors and standardize terminology.
        """
        if not self.model:
            logger.warning("Gemini model not initialized. Skipping LLM cleaning.")
            return text

        logger.info("Sending text to Gemini for refinement...")
        
        prompt = f"""
        You are an expert editor processing raw transcripts and documents.
        Your goal is to IMPROVE clarity and correctness WITHOUT summarizing or changing the meaning.

        Instructions:
        1. Fix transcription errors (e.g. "SQL" vs "sequel").
        2. Standardize technical terminology.
        3. Remove remaining stuttering or filler words.
        4. Fix grammar/sentence structure for readability.
        5. DO NOT summarize. Output length should be roughly same as input.
        6. Return ONLY the cleaned text.
        
        CRITICAL FORMATTING RULES:
        - Output MUST be PLAIN TEXT only
        - NO markdown formatting: no *, **, _, `, #, - (bullet markers), or numbered lists like "1."
        - NO special characters: no $, %, ^, or LaTeX
        - Write bullets as complete sentences separated by periods
        - Write lists as flowing prose
        
        Raw Text:
        {text}
        """

        try:
            response = self.model.generate_content(prompt)
            if response.text:
                cleaned = response.text.strip()
                # Post-process to remove any remaining markdown artifacts
                cleaned = self._strip_markdown_artifacts(cleaned)
                return cleaned
            return text
        except Exception as e:
            logger.error(f"Gemini cleaning failed: {e}")
            return text
    
    def _strip_markdown_artifacts(self, text: str) -> str:
        """
        Post-process to remove any markdown formatting that slipped through.
        """
        import re
        
        # Remove bold/italic markers (**, *, __, _)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
        text = re.sub(r'\*([^*]+)\*', r'\1', text)       # *italic*
        text = re.sub(r'__([^_]+)__', r'\1', text)       # __bold__
        text = re.sub(r'_([^_]+)_', r'\1', text)         # _italic_
        
        # Remove code markers (` and ```)
        text = re.sub(r'```[^`]*```', '', text)          # code blocks
        text = re.sub(r'`([^`]+)`', r'\1', text)         # inline code
        
        # Remove headers (#, ##, ###, etc.)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        
        # Remove remaining standalone asterisks/underscores at word boundaries
        text = re.sub(r'(?<!\w)\*+(?!\w)', ' ', text)
        text = re.sub(r'(?<!\w)_+(?!\w)', ' ', text)
        
        # Clean up any doubled spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text

    def clean_text(self, text: str, use_llm: bool = True) -> str:
        """
        Main orchestration method for text cleaning.
        """
        logger.info("Starting text cleaning...")
        
        # 1. Regex Pass (Fast)
        cleaned_text = self.clean_regex(text)
        
        # 2. LLM Pass (Smart)
        if use_llm and self.model:
            cleaned_text = self.clean_with_gemini(cleaned_text)
            
        logger.info("Text cleaning completed.")
        return cleaned_text

if __name__ == "__main__":
    # Test Block
    cleaner = TextCleaningService()
    
    raw_input = """

Transcript
0:11
Okay, welcome to Introductory Calculus. I  will start with some practical information  
0:18
and then I'll tell you a little bit  about the syllabus and what we will  
0:24
cover in this course and then give you  some examples of differential equations  
0:31
from physical sciences and then a little  bit of integration towards the end. So  
0:38
for many of you this might be the easiest  course here that you'll take in Oxford,  
0:46
but I think things will get progressively  harder so maybe in a couple of weeks it will  
0:52
be interesting to everybody if today's lecture  might be a bit too easy for some of you. Okay  
0:58
so let me tell you some practical information. So  we have 16 lectures. The lecture notes are online.
1:24
These are the lecture notes which were written  by Cath Wilkins - she taught this course for a  
1:38
few years until last year so we'll just follow  them I guess. I should have introduced myself  
1:48
at some point as the lecturer so you can call  me Dan my name is Dan Ciubotaru and we'll meet  
2:06
twice a week today is special just because  it's the first week. We'll meet on Mondays  
2:12
and Wednesdays at 10am, so not too early  and you'll have eight problem sheet. So  
2:27
the first two problem sheets are online.  The eight problem sheets you'll cover in  
2:32
four tutorials in your college. Okay so  four hours for tutorials. So I said the  
2:51
lecture notes are online, the reading list  is also online (so see online) the book that  
3:00
I like is Mary Boas's Mathematical Methods  in Physical Sciences you know this book and
3:21
most of your colleges should have a copy of  this. If not the university does as well. So  
3:34
this is this book is quite concise and it has  various examples from physics and engineering  
3:41
and science it also has the added advantage  that if unlike the other books on on the  
3:48
reading list if you drop this one on your foot  you might be able to to walk without seeing an  
3:55
orthopedic surgeon. All right, so that's that  - any questions about this? Okay, now syllabus
4:13
so the first half of the course - about  seven or eight lectures will be devoted  
4:28
to differential equations. So this is about  seven/eight lectures so of two kinds ordinary  
4:37
differential equations (ODEs) and partial  differential equations (or PDEs) so I'll  
5:04
give you some examples very soon. We'll look at  fairly easy examples of differential equations,  
5:12
we'll learn some techniques. It's a combination  solving them - it's a combination of science and  
5:18
art. You have to do some educated guesses at  some points but it's quite an interesting and  
5:26
very useful subject and then after that we'll  talk about line and double integrals and the  
5:42
reason these are useful is because we will  be able to compute arc lengths of curves and  
5:53
areas of various regions in the plane or  surfaces. So this is maybe three lectures
6:10
and then finally we'll do calculus  of functions in two variables. So  
6:27
this should be viewed as a gentle  introduction into multivariable   calculus. So among the things that we'll  do we'll look at various surfaces gradient
6:39
normal vectors will look at  Taylor's theorem in two variables,  
6:50
critical points and a little  bit of Lagrange multipliers,
6:57
which are useful for optimization problems. Okay,  now there is a lot of interaction between this  
7:12
course and other premlim courses that you will  take. So intro calculus will be directly useful in  
7:26
well obviously multivariable calculus as I said.  In a way it's a little bit unfair as we set up the  
7:40
work and we do some examples for in introduction  calculus but then the really cool result and  
7:45
theorems you prove in multivariable calculus, so  we just do a little bit of the ground work towards  
7:53
that. You also do these and they are also useful  in dynamics and in PDEs which you will do next  
8:05
term fourier series and PDEs. Now there is a lot  of interaction between intro calculus and analysis  
8:14
particularly analysis two which is what you do  next term so there will be quite a few results  
8:21
from analysis that will just say and not prove,  maybe prove some particular examples and so on,  
8:29
but real rigorous proofs you'll do in analysis  next term but then it all comes together when  
8:39
you revise or for your exams in Trinity. Okay so  there's that. Of course in Part A there will be  
8:51
lots of applied mathematics options that will  continue this. Differential equations is a big  
8:57
option, fluid and waves etc so this is a very  useful course it's also mandatory so you have  
9:04
to be here. So now let me give you some examples  of where all these might appear. Okay so all these
9:26
DEs, so what is an ordinary differential  equation? So this is an equation involving  
9:42
an independent variable, let's call it x and a  function of x which we call it y. So y this would  
10:11
be the dependent variable and the derivatives  of y with respect to x so for example dy/dx  
10:34
d^2y/dx^2 etc you know so the order of the highest  derivative that occurs we call that the order of  
10:47
the differential equation. So for example the  simplest so the simplest kind of ODE would be  
11:05
something of the form dy/dx equals some function  in x so dy/dx equals f(x) - you can solve that  
11:19
by direct integration so this can be solved  so y equals. So you can think of y as being  
11:40
the antiderivative of f(x) and then we we can  use integrations that's the simplest kind of  
11:47
differential equation that we can have and this is  the reason why we'll start the course by reviewing  
11:57
a little bit of integration techniques. But there  can be more interesting differential equations,  
12:06
so let me give you some examples from physical  sciences. So for example from mechanics,  
12:19
this is something that you have all seen,  you can have Newton's second law which  
12:33
says that the force is the mass times the  acceleration (so a is the acceleration).
12:45
But then the acceleration is a derivative. It is  the derivative of the velocity with respect to  
12:55
time. So that's already a differential equation  but it could be a second-order differential  
13:08
equation if you think that v is dr/dt where r is  the displacement. Then you get for example a is  
13:26
d^2r/dt^2 which is a second order differential  equation so that that's an easy example of how  
13:38
differential equations appear in mechanics. Well  you could also have differential equations in  
13:46
engineering, or if you have an electrical circuit.  So if I take a simple one, so a simple series  
14:05
circuit, which for example: an RLC circuit -  which means that it has the following components:  
14:17
it has R stands for resistor, so it has a resistor  R, it has an inductor L with inductance L and it  
14:35
has a capacitor with capacitance C and it has  a source of voltage something like a battery V.  
14:53
So I have a capacitor with C capacitance and the  resistor with R resistance and an inductor with L
15:14
inductance. So here are R, L and C are  constants they're independent of time
15:29
but then I'm interested for example in the  current across the circuit so this is the  
15:40
current across I(t) is the current across the  circuit which is a function of the time. So  
15:57
in terms of differential equations t the time  would be the independent variable and this I(t)  
16:03
for example is a dependent variable I can  also have Q(t) which is the charge across  
16:13
capacitor on the capacitor and the relation  between the two of them is that I=dQ/dt so  
16:36
Kirchoffs law says that the total voltage is  zero around the circuit. Which is in a another  
16:51
way saying the voltage V from the battery  which is a function of t equals the voltage  
17:02
across the resistor plus the voltage across the  resistor plus the voltage on the capacitor and  
17:10
now you write each one of them. The voltage  across the resistor by Ohm's law is R I(t),  
17:23
the one on the capacitor is just 1/C and for  the inductor is L dI/dt which is Faraday's Law.
17:54
So now I can express for example so I have an  equation involving V I and Q but I is dQ/dt  
18:09
so I can rewrite everything in terms of Q, for  example. So I can get a differential equation  
18:17
in Q which will be simply: this would be the  leading term dI/dt so L times dI/dt becomes L  
18:34
times d^2Q/dt^2 + RdQ/dt +1/C Q = V, so that  is a second order differential equation that  
18:58
appears in electrical circuits. Yeah so it's  second order because the highest derivative is  
19:09
of second order - it has constant coefficients  because the constants R,L and C are constant  
19:17
and it's what we'll call inhomogeneous because  this doesn't have to be zero. So those are the  
19:26
type of differential equations that we can we  can study and there are many other examples,  
19:35
so I'll leave one as an exercise for you. So  I'll tell you the problem is the rate at which  
19:52
a radioactive substance decays is proportional to  the remaining number of atoms. So I want you to,  
20:27
as an exercise, to write a differential equation  that describes this situation. Okay so we'll come  
20:37
back to things like this later. So what  the question is: what's the differential  
20:46
equation? Okay so as you progress along in this  course in the mathematics course here, you will  
21:07
encounter very very interesting and sophisticated  differential equations in applied mathematics,  
21:14
so we're just scratching the surface a little bit.  All right now, going back to what I what I said  
21:25
before - the simplest kind of ODE is dy/dx equals  f(x) which you can solve by integration so let me  
21:35
review a couple of facts about integration. So  one of the most useful techniques which I'm sure  
21:45
most of you are quite familiar with is integration  by parts. Okay so where does integration by parts  
22:05
come from? Well it comes from the product rule. If  I have two functions f and g and I multiply them  
22:31
and then I differentiate them so f times g prime  is f prime g plus f g prime, which means that f  
22:44
g f times g prime equals f times g prime minus  f prime times g and if I integrate both sides
22:57
then I end up with the integration by parts which  is f times g prime dx if they're functions of  
23:12
x. It equals f times g minus f prime times g dx.  Okay so this is the version indefinite integral's  
23:29
version, you can have a definite integral  version where you put the limits of integration.
23:38
So let me spell it out. So this is the  definite integral's version. Alright,  
23:55
so let's do a couple of examples. So the first  example - so suppose I want to integrate x^2  
24:18
sin(x). So this would solve, so this would  give this gives the solution to dy/dx equals  
24:40
x^2 sin(x) ok so in the integration by parts  you have to decide which one is f and which  
24:52
one's g. Now clearly I would like to decrease  the power here I know I can never get rid of  
25:00
the sine by differentiation so then maybe this  then I have to do this f and this is g prime
25:07
which means that g is -cos x so if I  call this integral I I is x squared  
25:23
times minus cos x and then minus  the derivative of f which is 2 x  
25:30
times minus cos x dx. This is minus x  squared cos x plus 2 times x cos x dx.
25:48
And now again this should be f and this should  be g prime of course x plus 2 times x sine x  
26:03
minus 2 times sine x dx. So please try to  follow through what I'm doing and let me  
26:17
know if I make a mistake. This is kind of  my nightmare to integrate integrals like  
26:23
this while I'm being filmed. Right exactly  what I like to do so 2x sin(x) and then  
26:36
minus cos(x) then plus C is this... so plus  plus thank you, as I said so C here denotes  
26:55
a constant because we're doing indefinite  integrals. All right let's do another example.
27:20
So again an indefinite integral:  2x minus 1 times Ln (x^2+1)dx. Ok.
27:36
What do you think? Which one should be f and which  one should be g or g prime. Say that again? Right  
27:57
so this I want to differentiate to get rid of the  logarithm, so I should call this f which means  
28:04
that this is going to be g prime, thank you and  that makes g: x squared minus x so this becomes  
28:14
x squared minus x ln (x^2+1) minus the integral  of x squared minus times the derivative of the  
28:28
natural log of x squared plus 1 which is 2x over  x squared plus 1 dx so and finally this term. What  
28:41
do I do here? Good so we we do long division, so  let's rewrite it first. This is x squared minus x  
28:56
ln x squared plus 1 and then minus 2x cubed minus  x squared over x squared plus 1 dx so I have to  
29:09
remember how to do long division, so I have x  cubed minus x, now depending how you learn this  
29:22
you will draw the the long division in different  ways so you just do it your way and I'll do it my  
29:30
way. So that's x minus x cubed minus x then minus  x squared minus 6 and that's minus 1. Ok so this  
29:57
means that x cubed minus x squared over x squared  plus 1 equals x minus 1 plus minus x plus 1.
30:10
Did you get the same thing?
30:17
Okay so let's call this integral J and now we  compute J. The integral of x minus 1 plus minus  
30:33
x plus 1 over x squared plus 1 dx which equals  x squared minus 1/2 x squared minus 6 and then  
30:49
how do I integrate this term? The fraction  so I should split x over x squared plus 1 dx.
31:07
Yeah and let me write the last term plus dx over x  squared plus 1. So this 1, the last term we should  
31:24
recognize that - what is it? It's arctan(x) or  tan inverse depending how you want to denote it  
31:32
this is arctan of x which is tan inverse of x.  Now what do we do with this we can substitute.
31:46
Yeah let's do that. So that we remember how to do  substitutions. You might just look at it and know  
31:55
what it is right, but just to review substitution  if I said u equals x squared plus 1 then du equals  
32:04
2x dx, so du/dx equals 2x which means that this  is 1/2 d u / u which is 1/2 Ln of u which is 1/2  
32:25
Ln of x squared plus 1 that you might have guessed  just because you have enough practice some of you.  
32:35
Okay so now let's put them all together.  So J is 1/2 x squared minus x minus 1/2  
32:46
Ln x squared plus 1 plus tan inverse of x + some  constant, which means that the original integral,  
33:01
the integral in the beginning which I should  have called I so that I don't have to roll  
33:13
down the boards, that equals x squared minus x  Ln x squared plus 1 minus twice this. So minus  
33:32
x squared plus 2x plus Ln x squared plus  1 minus tan inverse x and then plus 2c.
33:48
Thank you. Any other mistakes? Alright.
33:56
Okay so that's a that's an intro. There are cases  when integration by parts will not simplify either  
34:18
of the two functions f and g but what happens is  if you do it twice then you sort of come back to  
34:24
what you started with. So the typical example is  I equals the integral e to the x times sine x dx.  
34:42
So maybe we don't need to go through the entire  calculation - this is in the lecture notes as  
34:57
well - but how would you solve it? Right so  you do it so for example I can say that this  
35:12
is g prime and this is f and then I integrate  I get cos and then I do it again and I will end  
35:22
up with some expression - they seem to grow  and then I solve for it. So you do this and  
35:29
you get the answer to be something like 1/2 e  to the x sin(x) minus cos x then plus constant.
35:44
Okay so another type of example which  are more difficult are the ones which  
36:00
you cannot solve in just one go  but you have to find a recursive   formula. So I'll just do an example like  that. You've seen other examples before  
36:11
so this is when we get a reduction or if  you want to call it a recursive formula.
36:24
So I start, suppose I'm looking at this integral:  cosine to the n x dx. Now I want to label this  
36:46
integral I(n) because I'm going to get a formula  of I(n) in terms of I(n-1) or I(n-2) etc. Now  
37:00
there is not much choice here what you should  call f and what you should call g so I'm going  
37:07
to just do it. So this is cos^(n-1) x times cos  x dx so this is f and this is g prime, then we  
37:20
get cos n minus 1 x sin(x) minus the integral.  Now I need to differentiate f so (n-1) cos n  
37:35
minus 2 x and then minus sine x and then another  sine x dx, which equals cos n minus 1 x sine x.
37:55
- n - 1 times, or maybe I'll make it a plus, and  minus 2 x sine squared x dx. So if I write it like  
38:13
that what do you do now? You write sine squared as  1 minus cos squared x, which then gives you cos n  
38:30
minus 1 x sine x plus n minus 1, the integral of  cos n minus 2 x dx minus n minus 1 the integral of  
38:46
cos n squared x dxm so now I recognize that this  is the integral of course n minus 2 is I sub n  
39:00
minus 2 and the integral of cos, and this is I(n)  so I have I(n) equals that so if I solve for I(n)  
39:14
we get I(n) that n I(n) equals cos^(n-1)(x)sin(x)+  (n-1)I(n-2), which gives me the recursive formula
39:47
I(n) equals 1 over n cos (n minus 1) x  sine x plus n minus 1 over n. So this  
40:07
is true for all n greater than or equal  to 2. Okay now if I want to know all of  
40:33
these integrals I(n) using this formula  - what else do I need to know? I(0) and  
40:43
I(1) because it drops down by 2. So let's  compute I(0) and I(1), so I(0) would be just  
41:02
the integral dx which is x plus C, and I(1)  is the integral of cos x dx which is sine x
41:17
plus C and now with this you can  you can get any integral you want,  
41:27
for example if you want to get I don't know I(6),
41:39
you just follow that and you get that  it's 1/6 cos^5(x)sin(x) plus 5 over  
41:48
6 times I(4) which is 1 over 6 cos^5(x) sine x  plus 5 over 6 times I(4) is 1/4 cos cubed x sine x  
42:16
plus 3/4 I(2), then what is I(2) is 1/2 cos x sine  x plus one-half I zero but I zero is x so you put  
42:40
your substitute this in there and I get an I six  is 1/6 cos to the fifth x sine x plus five over 24  
42:54
cos cubed x sine x plus 5 times 3 times 1 over 6  times 4 times 2 cos x sine x plus 5 times 3 over
43:17
over 6 times 4 times 2 x, so it has I think  you can you can probably cook up a general  
43:37
formula using this example - you see how  it goes. So if I asked you to write a sum  
43:45
involving all the terms I think you can you can  get the coefficients of each term inductively.
43:52
Okay so this is a quick review of integration  by parts. If you're not fully comfortable with  
44:06
these examples or similar examples, then  get get an integration textbook and do a  
44:14
few more examples with integration by parts,  substitutions and so on because in solving  
44:22
differential equations we'll learn a lot of  techniques but ultimately you will have to  
44:27
integrate some functions so you should be able  to do that. What we learn is how to reduce the  
44:34
problem to integrating various functions  but you'll have to be able to do that.
44:40
Okay so we discussed about  the simplest kind of these  
44:50
which can be solved just by direct  integration. The next simplest of
44:59
these are the so-called separable.
45:23
so we had the case dy/dx equals f(x)  which you can just integrate the next  
45:32
case would be dy/dx equals a(x) b(y).  So what I mean by that is that this is  
45:48
a function in only x and similar  b of y is a function of y only.
46:04
If you have a situation like that then you can  reduce it to the direct integration with one  
46:17
simple trick. If b(y) is not zero then you divide  by it and you get 1 over b(y) dy dx equals a(x),
46:34
and now you can integrate just as we did  before. So you'll get then the integral
46:52
so the left-hand side is the integral dy  over b(y) and the right-hand side is a(x)dx  
47:08
and now you have to direct integrations  which hopefully we can we can solve,  
47:17
right. The type of integrals that we have  in this course will be the kind for which  
47:23
you can apply integration by parts or some  other techniques and solve them if I if I  
47:28
were to write an arbitrary function there and  ask you how to integrate it then we can't do  
47:35
that in a closed formula. Okay so here's  an example: find the general solution to
47:54
the separable differential equation. So the  hint is already in the problem that this is  
48:14
a separable differential equation x times  y squared minus 1 plus y x squared minus  
48:23
1 dy/dx equals to 0 and x is between 0 & 1 to  avoid some issues about continuity or whatnot.
48:40
Okay, how do you separate this differential  equation? How do you separate the variables?  
48:55
Correct, so I think you're about two steps  ahead of me. It's correct but let me do it  
49:13
step by step. So what I will do is first  isolate that so I have y x squared minus  
49:20
one dy/dx equals minus xy squared minus one  and then separate the variables, as the name  
49:34
suggests. You have y over y squared minus one  dy/dx equals minus x over x squared minus one.
49:48
Okay what do we do now? Correct, so if we look  at this then, so we integrate, let's integrate,  
50:28
well let me write one more, so we integrate this  and we get y over y squared minus one dy equals  
50:38
minus x over x squared minus 1 dx so now we could  do substitution as we did before but I think we  
50:53
know how to do it, this looks like the derivative  of a logarithm. So if I differentiate ln of x  
51:00
squared minus 1 then I get 2x over x squared minus  1, so except x is between 0 & 1 so maybe it's  
51:16
better to write this as 1 x over 1 minus x squared  and get get rid of the minus sign. So then I'll do  
51:27
1 minus x squared minus 2x over 1 minus x squared  so then this is minus Ln of 1 minus x squared
51:45
and a half and then plus a C. Whereas  here I will have to put absolute values  
51:55
because I don't know. It's 1/2 Ln so y  squared minus 1 in absolute values right.
52:07
Now the easiest way to write this is to get rid  of the logarithm by moving this to the other side.  
52:16
Using the properties of the logarithmic, so let's  do that. So I have 1/2. If I move the logarithm in  
52:27
x to the left hand side then I use the property,  well it doesn't matter much, it equals C which  
52:50
means that the equation will be y squared minus  1 times 1 minus x squared absolute value equals  
53:03
it would be e to C squared or e to to C which I  can just call another kind of C and this would  
53:20
be a positive number so the equation then  that we get is so the the answer then is
53:47
where C is positive. But I can relax that, this  is always positive because 1 minus x squared  
53:59
is always positive, because I'm assuming x is  between 0 & 1 but I can rewrite the answer in  
54:06
a nicer form by dropping the absolute value and  dropping the assumption on C. So another way of  
54:19
this for uniformity, I'll write it as 1 minus  y squared equals C so 1 minus y squared times  
54:38
1 minus x squared equals C. No assumption on C  except so C could be both positive or negative  
54:48
except in this formula it looks like it can't  be 0, right? This here I got an exponential  
54:57
which is never 0 so this is positive, I drop the  absolute value and now C can also be negative but  
55:11
somehow 0 is missing. How is that possible?  That doesn't look like solid mathematics?
55:17
Yes?
55:24
That's right. Okay, so where did I lose  that case? Right here. So I divided by  
55:37
y squared minus one. I did that ignoring  the case when y squared minus one is zero,  
55:46
so note so let's call this star here so in  star y -1 is y squared minus 1 is not 0 but  
56:04
if we need to allow that because it is possible  for y to be plus or minus 1 for example. If y  
56:14
is the constant function 1 then this is 0  and dy/dx is 0, so that's okay. So if we  
56:23
allow if y is plus minus 1 is included in the  solution if we allow C to be 0 in the answer.
56:52
So then the bottom line is that the answer is  
56:58
this implicit equation in y and x  where C can be any constant. Good.
57:17
So be careful when when you divide by  the function in y, as I said here you  
57:28
can do that if you know that's not zero,  but sometimes you get solutions from it  
57:33
being zero so you have to be careful there. All  right, that's the end of the first lecture I'll  
57:38
see you tomorrow for for the second lecture  and we'll do more differential equations!
    """
    print(f"Original: {raw_input}\n")
    
    # regex_only = cleaner.clean_regex(raw_input)
    # print(f"Regex Only: {regex_only}\n")
    
    final_output = cleaner.clean_text(raw_input)
    print(f"Final Output: {final_output[:500]}...") # Print preview

    output_file = "cleaned_output.txt"
    with open(output_file, "w") as f:
        f.write(final_output)
    print(f"\nFull cleaned text saved to {output_file}")
